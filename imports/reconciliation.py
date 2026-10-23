"""Reconciled legacy import: private preview first, explicit confirmation second.

Resolutions are supplied by the operator, never embedded in source or fixtures.
No live inventory is changed while producing a preview.
"""

import hashlib
import hmac
import json
from collections import defaultdict
from datetime import date

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models import Sum
from django.utils import timezone

from inventory.models import (
    AuditEvent,
    ImportBatch,
    ImportPreview,
    Location,
    Movement,
    MovementLine,
    MovementLineSource,
    OpeningBalance,
    Reference,
    Sector,
)
from inventory.services import require_administrator, resolve_person

from .excel import integer, normalized


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def source_digest(batch, rows):
    return digest({
        "sha256": batch.sha256, "summary": batch.summary,
        "rows": [{"id": row.pk, "sheet": row.sheet, "row": row.row_number,
                  "raw": row.raw_data, "opening": row.opening_stock,
                  "reported": row.reported_stock, "candidate": row.reconciled_stock}
                 for row in rows],
    })


def target_digest():
    return digest({
        "references": list(Reference.objects.order_by("pk").values()),
        "locations": list(Location.objects.order_by("pk").values()),
        "sectors": list(Sector.objects.order_by("pk").values()),
        "movements": list(Movement.objects.order_by("pk").values_list("pk", "status")),
        "openings": list(OpeningBalance.objects.order_by("pk").values_list("pk", "quantity")),
    })


def _identity(name):
    # Keep accents significant; only spacing and letter case identify duplicates.
    return " ".join(name.split()).casefold()


def _prepare(batch, rows, decisions):
    errors, warnings = [], []
    if decisions.get("source_sha256") not in (None, batch.sha256):
        errors.append("As decisões não pertencem ao ficheiro de origem deste lote.")
    if decisions.get("schema_version") != 1:
        errors.append("Versão das decisões inválida.")
    annotations = decisions.get("annotations", {})
    document_headers = decisions.get("document_headers", {})
    if not isinstance(annotations, dict) or not isinstance(document_headers, dict):
        raise ValidationError("Anotações e cabeçalhos de documento devem ser objetos JSON.")
    if Reference.objects.exists() or OpeningBalance.objects.exists() or Movement.objects.exists():
        errors.append("A importação inicial exige catálogo e histórico operacional vazios.")
    if batch.status == ImportBatch.Status.REJECTED:
        errors.append("O lote foi rejeitado.")
    if not rows:
        errors.append("O lote não contém linhas Stock.")
    headers = batch.summary.get("source_headers", {})
    opening_date = headers.get("opening_calendar_date")
    try:
        date.fromisoformat(opening_date)
    except (ValueError, TypeError):
        errors.append("Data do saldo inicial inválida.")
    source_headers = headers.get("movement_columns", {})
    used_annotations, used_documents = set(), set()
    parsed_headers = {}
    for letter, header in source_headers.items():
        when = header.get("calendar_date")
        label = header.get("label", {}).get("value")
        person = header.get("person", {}).get("value")
        try:
            date.fromisoformat(when)
        except (TypeError, ValueError):
            errors.append(f"Data inválida na coluna {letter}.")
        if not isinstance(label, str) or not label.strip():
            errors.append(f"Etiqueta inválida na coluna {letter}.")
        elif len(label) > 250:
            errors.append(f"Etiqueta demasiado longa na coluna {letter}.")
        doc = document_headers.get(letter)
        document_number = ""
        if doc is not None:
            if not isinstance(doc, dict) or doc.get("original_value") != person or not str(doc.get("document_number", "")).strip() or not doc.get("reason"):
                errors.append(f"Decisão de documento não corresponde ao cabeçalho {letter}.")
            else:
                document_number = str(doc["document_number"]).strip()
                used_documents.add(letter)
                if len(document_number) > 250:
                    errors.append(f"Número de documento demasiado longo na coluna {letter}.")
            person = None
        elif not isinstance(person, str) or not person.strip():
            errors.append(f"Cabeçalho de pessoa por resolver na coluna {letter}.")
        elif len(" ".join(person.split())) > 200:
            errors.append(f"Nome de pessoa demasiado longo na coluna {letter}.")
        parsed_headers[letter] = {
            "column": header.get("column"), "date": when,
            "label": label, "person": person, "document_number": document_number,
            "source_header": header,
        }

    groups = {}
    unknown_openings, annotation_count = 0, 0
    used_columns = set()
    negative_entries = positive_exits = 0
    known_locations = set(Location.objects.values_list("name", flat=True))
    for row in rows:
        raw, cells = row.raw_data, row.raw_data.get("cells", {})
        name = cells.get("A", {}).get("value")
        location = raw.get("mapped_location")
        if row.sheet != "Stock" or raw.get("sheet") != "Stock":
            errors.append(f"A linha {row.row_number} não pertence a Stock.")
        if not isinstance(name, str) or not name.strip() or len(name) > 250:
            errors.append(f"Designação inválida na linha {row.row_number}.")
            name = str(name or "")
        if location not in known_locations:
            errors.append(f"Localização sem correspondência na linha {row.row_number}.")
        capacity_value = cells.get("B", {}).get("value")
        capacity = integer(capacity_value)
        if capacity_value is not None and (capacity is None or capacity <= 0):
            errors.append(f"Capacidade inválida na linha {row.row_number}.")
        stock = integer(row.reported_stock)
        if stock is None or stock < 0:
            errors.append(f"Stock oficial inválido na linha {row.row_number}.")
        source_stock_cell = cells.get("C", {})
        source_stock = integer(source_stock_cell.get("cached_value")
                               if source_stock_cell.get("excel_type") == "f"
                               else source_stock_cell.get("value"))
        if stock != source_stock:
            errors.append(f"O stock preparado difere da célula de origem na linha {row.row_number}.")
        opening = integer(cells.get("E", {}).get("value"))
        if cells.get("E", {}).get("value") is not None and opening is None:
            errors.append(f"Saldo inicial inválido na linha {row.row_number}.")
        entries, signed_total = [], 0
        for source in raw.get("movements", []):
            cell = source.get("cell", {})
            coordinate, value = cell.get("coordinate"), cell.get("value")
            letter = source.get("header_column")
            if letter not in parsed_headers:
                errors.append(f"Movimento sem cabeçalho na célula {coordinate}.")
                continue
            used_columns.add(letter)
            quantity = integer(value)
            annotation = ""
            if quantity is None:
                resolution = annotations.get(coordinate)
                if not isinstance(resolution, dict) or resolution.get("original_value") != value or not resolution.get("reason"):
                    errors.append(f"Valor não quantitativo por resolver em {coordinate}.")
                else:
                    annotation = resolution["reason"]
                    used_annotations.add(coordinate)
                    annotation_count += 1
            else:
                signed_total += quantity
                label = normalized(parsed_headers[letter]["label"])
                if label == "entrada" and quantity < 0:
                    negative_entries += 1
                if label in ("saida", "saída") and quantity > 0:
                    positive_exits += 1
            entries.append({"column": letter, "coordinate": coordinate,
                            "quantity": quantity, "raw_value": value,
                            "annotation": annotation, "source_cell": cell})
        if opening is None:
            unknown_openings += 1
            if decisions.get("blank_opening_policy") != "unknown_derived":
                errors.append("Inventários vazios exigem uma política explícita de saldo inferido.")
            baseline = (stock or 0) - signed_total
            if baseline < 0:
                errors.append(f"Saldo inicial inferido negativo na linha {row.row_number}.")
        else:
            baseline = opening
        reconciled = baseline + signed_total
        if stock is not None and reconciled != stock:
            errors.append(f"Saldo divergente na linha {row.row_number}.")
        detail = {
            "legacy_row_id": row.pk, "row_number": row.row_number,
            "opening_quantity": opening, "reconciliation_quantity": baseline,
            "movement_total": signed_total, "stock": stock, "entries": entries,
        }
        key = (location, _identity(name))
        if key not in groups:
            groups[key] = {"name": " ".join(name.split()), "location": location,
                           "capacity": capacity, "opening_known": True,
                           "opening_quantity": 0, "reconciliation_quantity": 0,
                           "movement_total": 0, "stock": 0,
                           "source_rows": [], "source_details": []}
        group = groups[key]
        if group["capacity"] != capacity:
            errors.append(f"Capacidades incompatíveis em referências duplicadas na linha {row.row_number}.")
        if opening is None:
            group["opening_known"] = False
            group["opening_quantity"] = None
        elif group["opening_quantity"] is not None:
            group["opening_quantity"] += opening
        group["reconciliation_quantity"] += baseline
        group["movement_total"] += signed_total
        group["stock"] += stock or 0
        group["source_rows"].append(row.row_number)
        group["source_details"].append(detail)
    if set(annotations) != used_annotations:
        errors.append("Existem decisões de anotação sem correspondência exata na fonte.")
    if set(document_headers) != used_documents:
        errors.append("Existem decisões de documento sem correspondência exata na fonte.")
    # Any unfamiliar parser error blocks publication, rather than disappearing
    # merely because the known source exceptions have been explained.
    handled = {"nonnumeric_movement", "invalid_person_header", "stock_reconciliation_mismatch"}
    for issue in batch.summary.get("issues", []):
        if issue.get("severity") == "error" and issue.get("code") not in handled:
            errors.append(f"Erro de origem por resolver: {issue.get('code')} ({issue.get('cell')}).")
    result = list(groups.values())
    total = sum(group["stock"] for group in result)
    if integer(decisions.get("expected_total")) != total:
        errors.append("O total não coincide com o total oficial declarado nas decisões.")
    if integer(decisions.get("expected_references")) != len(result):
        errors.append("O número de referências não coincide com o valor oficial declarado.")
    if unknown_openings:
        warnings.append("Saldos iniciais vazios permanecem desconhecidos; o saldo de reconciliação é inferido, não uma contagem confirmada.")
    if len(result) < len(rows):
        warnings.append("Referências duplicadas serão unificadas, mantendo cada linha e célula de origem.")
    line_keys = {(index, entry["column"]) for index, group in enumerate(result)
                 for detail in group["source_details"] for entry in detail["entries"]}
    summary = {
        "reference_count": len(result), "row_count": len(rows), "total_stock": total,
        "movement_count": len(used_columns), "line_count": len(line_keys),
        "unknown_openings": unknown_openings, "annotations": annotation_count,
        "unidentified_people": sum(not parsed_headers[c]["person"] for c in used_columns),
        "negative_entries": negative_entries, "positive_exits": positive_exits,
        "errors": list(dict.fromkeys(errors)), "warnings": warnings,
        "ready": not errors, "source_sha256": batch.sha256,
        "opening_date": opening_date,
    }
    return summary, result, parsed_headers


def _preview_digest(source, target, decisions, summary, rows):
    return digest({"source": source, "target": target, "decisions": decisions,
                   "summary": summary, "rows": rows})


@transaction.atomic
def build_preview(batch_id, resolutions, *, actor):
    require_administrator(actor)
    if not isinstance(resolutions, dict):
        raise ValidationError("As decisões devem ser um objeto JSON.")
    batch = ImportBatch.objects.select_for_update().get(pk=batch_id)
    if batch.status == ImportBatch.Status.IMPORTED:
        raise ValidationError("O lote já foi publicado; consulte o relatório da publicação existente.")
    rows = list(batch.rows.order_by("row_number", "pk"))
    summary, groups, _ = _prepare(batch, rows, resolutions)
    source, target = source_digest(batch, rows), target_digest()
    preview = ImportPreview.objects.create(
        import_batch=batch, decisions=resolutions, summary=summary, rows=groups,
        source_digest=source, target_digest=target,
        reconciliation_digest=_preview_digest(source, target, resolutions, summary, groups),
        created_by=actor,
    )
    if summary["ready"]:
        batch.status = ImportBatch.Status.RECONCILED
        batch.save(update_fields=["status"])
    AuditEvent.objects.create(actor=actor, action="import.previewed", details={
        "preview_id": str(preview.pk), "source_sha256": batch.sha256,
        "ready": summary["ready"], "reconciliation_digest": preview.reconciliation_digest,
    })
    return preview


@transaction.atomic
def publish_preview(preview_id, *, actor, confirmation_token):
    require_administrator(actor)
    # The catalogue writer uses this same lock: no concurrent create can race
    # the empty-catalogue check while the initial migration is being published.
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [73194621])
    preview = ImportPreview.objects.select_for_update().select_related("import_batch").get(pk=preview_id)
    batch = ImportBatch.objects.select_for_update().get(pk=preview.import_batch_id)
    if not hmac.compare_digest(str(preview.confirmation_token), str(confirmation_token)):
        raise ValidationError("A confirmação não corresponde à pré-visualização apresentada.")
    if preview.published_at is not None:
        return {**preview.validation_report, "already_published": True}
    if batch.status == ImportBatch.Status.IMPORTED:
        existing = batch.previews.filter(published_at__isnull=False).first()
        if existing:
            return {**existing.validation_report, "already_published": True}
        raise ValidationError("O lote já foi publicado.")
    stored_digest = _preview_digest(preview.source_digest, preview.target_digest,
                                    preview.decisions, preview.summary, preview.rows)
    if stored_digest != preview.reconciliation_digest:
        raise ValidationError("O conteúdo da pré-visualização foi alterado. Gere uma nova pré-visualização.")
    rows = list(batch.rows.select_for_update().order_by("row_number", "pk"))
    source, target = source_digest(batch, rows), target_digest()
    summary, groups, headers = _prepare(batch, rows, preview.decisions)
    reconciliation = _preview_digest(source, target, preview.decisions, summary, groups)
    if source != preview.source_digest or target != preview.target_digest or reconciliation != preview.reconciliation_digest:
        raise ValidationError("A pré-visualização está desatualizada ou foi alterada. Gere e confirme uma nova pré-visualização.")
    if not summary["ready"] or not preview.summary.get("ready"):
        raise ValidationError("Existem erros de reconciliação; a publicação está bloqueada.")
    source_by_id = {row.pk: row for row in rows}
    references = {}
    locations = {location.name: location for location in Location.objects.all()}
    for index, group in enumerate(groups, start=1):
        reference = Reference.objects.create(
            code=f"GAR-{index:04d}", name=group["name"], location=locations[group["location"]],
            sector=None, box_capacity=group["capacity"], current_stock=group["stock"],
            minimum=None, active=True,
        )
        references[index - 1] = reference
        for detail in group["source_details"]:
            row = source_by_id[detail["legacy_row_id"]]
            row.reference = reference
            row.save(update_fields=["reference"])
            unknown = detail["opening_quantity"] is None
            OpeningBalance.objects.create(
                reference=reference, legacy_row=row, date=summary["opening_date"],
                quantity=detail["opening_quantity"],
                reconciliation_quantity=detail["reconciliation_quantity"],
                basis="derived_unknown" if unknown else "counted",
                explanation=("Contagem inicial ausente na fonte. Saldo de reconciliação inferido como stock oficial menos movimentos; não representa uma contagem confirmada."
                             if unknown else "Quantidade de inventário explicitamente registada na fonte."),
            )
    by_column = defaultdict(list)
    for index, group in enumerate(groups):
        for detail in group["source_details"]:
            for entry in detail["entries"]:
                by_column[entry["column"]].append((index, detail, entry))
    imported_movements = imported_lines = source_cells = 0
    for column in sorted(by_column, key=lambda c: (headers[c]["date"], headers[c]["column"])):
        header = headers[column]
        person = resolve_person(header["person"]) if header["person"] else None
        movement = Movement.objects.create(
            kind=Movement.Kind.LEGACY, date=header["date"], occurred_at=None,
            person=person, original_label=header["label"], document_number=header["document_number"],
            source_metadata={"sheet": "Stock", "column": column,
                             "header": header["source_header"],
                             "annotations": [{"coordinate": entry["coordinate"], "value": entry["raw_value"], "decision": entry["annotation"]}
                                             for _, _, entry in by_column[column] if entry["quantity"] is None],
                             "document_decision": preview.decisions.get("document_headers", {}).get(column)},
            import_batch=batch, source_column=header["column"], created_by=actor,
            validation=Movement.Validation.IMPORT,
        )
        grouped_entries = defaultdict(list)
        for group_index, detail, entry in by_column[column]:
            grouped_entries[group_index].append((detail, entry))
        for group_index, sources in grouped_entries.items():
            reference = references[group_index]
            line = MovementLine.objects.create(
                movement=movement, reference=reference,
                quantity=sum(entry["quantity"] or 0 for _, entry in sources),
                reference_name=reference.name, box_capacity=reference.box_capacity,
                # Intraday order is unknown: do not fabricate before/after snapshots.
                stock_before=None, stock_after=None,
                legacy_row=source_by_id[sources[0][0]["legacy_row_id"]],
            )
            for detail, entry in sources:
                MovementLineSource.objects.create(
                    line=line, legacy_row=source_by_id[detail["legacy_row_id"]],
                    coordinate=entry["coordinate"], quantity=entry["quantity"], raw_value=entry["raw_value"],
                )
                source_cells += 1
            imported_lines += 1
        movement.status = Movement.Status.CONFIRMED
        movement.save(update_fields=["status"])
        imported_movements += 1
    # Validate individual balances against the ledger, never only the global sum.
    validation_rows = []
    for index, group in enumerate(groups):
        reference = references[index]
        movement_total = reference.movement_lines.aggregate(total=Sum("quantity"))["total"] or 0
        opening_total = reference.opening_balances.aggregate(total=Sum("reconciliation_quantity"))["total"] or 0
        if opening_total + movement_total != reference.current_stock or reference.current_stock != group["stock"]:
            raise ValidationError("Falha na reconciliação individual durante a publicação; nenhuma alteração foi guardada.")
        validation_rows.append({"code": reference.code, "name": reference.name,
                                "stock": reference.current_stock, "reconciled": opening_total + movement_total})
    total = Reference.objects.aggregate(total=Sum("current_stock"))["total"] or 0
    if total != summary["total_stock"]:
        raise ValidationError("O total final diverge da pré-visualização; publicação revertida.")
    report = {
        **summary, "published": True, "already_published": False,
        "preview_id": str(preview.pk), "reconciliation_digest": preview.reconciliation_digest,
        "imported_movements": imported_movements, "imported_lines": imported_lines,
        "source_cells": source_cells, "validation_rows": validation_rows,
        "individual_mismatches": 0,
    }
    batch.status = ImportBatch.Status.IMPORTED
    batch.save(update_fields=["status"])
    preview.published_at = timezone.now()
    preview.validation_report = report
    preview.save(update_fields=["published_at", "validation_report"])
    AuditEvent.objects.create(actor=actor, action="import.published", details={
        "preview_id": str(preview.pk), "reconciliation_digest": preview.reconciliation_digest,
        "reference_count": len(groups), "total_stock": total,
    })
    return report
