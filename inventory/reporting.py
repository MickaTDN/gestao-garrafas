"""Numbered immutable evidence and strictly byte-identical file reproductions."""

import hashlib

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.db.models import BooleanField, Case, Exists, OuterRef, Q, Value, When

from accounts.permissions import capabilities, require_access, visible_movements

from .catalog import catalogue_lock
from .models import AuditEvent, Document, Movement, ReportFile, ReportSequence, ReportTemplate
from .pdf_v3 import asset_key, rendering_assets


def issued_filter():
    return Q(payload__isnull=False) | Q(report_file__isnull=False)


def available_filter():
    return Q(payload__isnull=False) | Q(report_file__payload__isnull=False)


def with_file_status(queryset):
    return queryset.annotate(
        file_present=Case(
            When(payload__isnull=False, then=Value(True)),
            default=Exists(
                ReportFile.objects.filter(document_id=OuterRef("pk"), payload__isnull=False)
            ),
            output_field=BooleanField(),
        )
    ).defer("payload")


def document_payload(document):
    if document.payload is not None:
        return bytes(document.payload)
    return bytes(
        ReportFile.objects.filter(document=document).values_list("payload", flat=True).first()
        or b""
    )


def allocate_number(year):
    if not connection.in_atomic_block:
        raise RuntimeError("A numeração exige a transação da confirmação.")
    sequence, _ = ReportSequence.objects.select_for_update().get_or_create(year=year)
    sequence.last_number += 1
    sequence.save(update_fields=["last_number"])
    return sequence.last_number


def template_key():
    assets = rendering_assets()
    key = asset_key(assets)
    ReportTemplate.objects.get_or_create(key=key, defaults={"assets": assets})
    return key


def authorized_document(actor, document_id):
    require_access(actor, "reports_view")
    movements = visible_movements(actor, Movement.objects.filter(status="confirmed"))
    try:
        return Document.objects.select_related("movement").get(
            pk=document_id, kind="pdf", movement__in=movements
        )
    except Document.DoesNotExist as error:
        raise PermissionDenied("Este relatório não está autorizado para o seu perfil.") from error


def can_regenerate(actor, document):
    allowed = capabilities(actor)
    return "reports_manage" in allowed or (
        "reports_view" in allowed
        and document.movement.created_by_id == actor.pk
        and document.movement.kind in allowed
    )


def reproduce(document):
    from .documents import DocumentIntegrityError, render_pdf, verified_bytes

    snapshot = document.metadata
    if (
        snapshot.get("presentation") != 3
        or not snapshot.get("template_key")
        or not snapshot.get("report_number")
    ):
        raise ValidationError(
            "Este relatório anterior não possui uma receita de reprodução fiel. O único exemplar será conservado."
        )
    signature = None
    if snapshot.get("validation") == "signed":
        try:
            signature = verified_bytes(
                document.movement.documents.get(
                    kind="signature", payload__isnull=False, sha256=snapshot.get("signature_sha256")
                )
            )
        except (Document.DoesNotExist, DocumentIntegrityError, ValueError) as error:
            raise ValidationError(
                "A evidência original de assinatura não está disponível; conserve o PDF existente."
            ) from error
    try:
        payload = render_pdf(snapshot, signature)
    except (ValueError, ReportTemplate.DoesNotExist) as error:
        raise ValidationError(
            "O modelo original não está disponível. O exemplar existente será conservado."
        ) from error
    if hashlib.sha256(payload).hexdigest() != document.sha256 or len(payload) != document.byte_size:
        raise ValidationError(
            "Não é possível reproduzir este PDF byte a byte. O exemplar existente será conservado; use a versão de emissão original."
        )
    return payload


@transaction.atomic
def delete_pdf(*, actor, document_id):
    require_access(actor, "reports_manage")
    catalogue_lock()
    document = authorized_document(actor, document_id)
    try:
        file = ReportFile.objects.select_for_update().get(document=document)
    except ReportFile.DoesNotExist as error:
        raise ValidationError(
            "Este exemplar histórico é imutável e não dispõe de reprodução fiel; não pode ser eliminado."
        ) from error
    reproduce(document)  # Demonstrate exact reproduction BEFORE destroying the only file.
    if file.payload is None:
        return document
    from .documents import verified_bytes

    verified_bytes(document)
    with connection.cursor() as cursor:
        cursor.execute("UPDATE inventory_reportfile SET payload=NULL WHERE id=%s", [file.pk])
    AuditEvent.objects.create(
        actor=actor,
        movement=document.movement,
        action="document.file_deleted",
        details={
            "document_id": document.pk,
            "sha256": document.sha256,
            "number": document.metadata["report_number"],
        },
    )
    return document


@transaction.atomic
def regenerate_pdf(*, actor, document_id):
    require_access(actor, "reports_view")
    catalogue_lock()
    document = authorized_document(actor, document_id)
    if not can_regenerate(actor, document):
        raise PermissionDenied("O seu perfil permite consultar mas não regenerar este relatório.")
    try:
        file = ReportFile.objects.select_for_update().get(document=document)
    except ReportFile.DoesNotExist as error:
        raise ValidationError(
            "Este relatório histórico não pode ser reproduzido fielmente."
        ) from error
    if file.payload is not None:
        from .documents import verified_bytes

        verified_bytes(document)
        document.file_was_regenerated = False
        return document
    payload = reproduce(document)
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE inventory_reportfile SET payload=%s, reproductions=reproductions+1 WHERE id=%s",
            [payload, file.pk],
        )
    AuditEvent.objects.create(
        actor=actor,
        movement=document.movement,
        action="document.file_regenerated",
        details={
            "document_id": document.pk,
            "sha256": document.sha256,
            "number": document.metadata["report_number"],
            "byte_identical": True,
        },
    )
    document.file_was_regenerated = True
    return document
