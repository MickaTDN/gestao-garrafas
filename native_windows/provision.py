"""One-time provisioning, only in the empty native database, credentials via stdin."""

import json
import os
import sys


def main():
    import django

    django.setup()
    from django.contrib.auth.password_validation import validate_password
    from django.db import transaction
    from django.utils import timezone

    from accounts.models import User
    from inventory.models import AuditEvent, ImportBatch, Location, OpeningBalance, Reference

    if os.environ.get("GVA_MAINTENANCE") != "1":
        raise RuntimeError("Apenas a inicialização administrativa pode criar a conta inicial.")
    request = json.load(sys.stdin)
    with transaction.atomic():
        if User.objects.exists() or Reference.objects.exists() or ImportBatch.objects.exists():
            raise RuntimeError("A inicialização não pode substituir dados existentes.")
        user = User(username=request["username"], role="admin")
        validate_password(request["password"], user)
        user.set_password(request["password"])
        user.save()
        if request["synthetic"]:
            location = Location.objects.order_by("pk").first()
            for code, name, capacity, stock in [
                ("SYN-C-1", "Exemplo fictício Azul", 6, 24),
                ("SYN-C-2", "Exemplo fictício Verde", 12, 0),
                ("SYN-C-3", "Exemplo fictício sem capacidade", None, 9),
            ]:
                ref = Reference.objects.create(
                    code=code,
                    name=name,
                    box_capacity=capacity,
                    current_stock=stock,
                    location=location,
                )
                OpeningBalance.objects.create(
                    reference=ref,
                    quantity=stock,
                    date=timezone.localdate(),
                    explanation="Validação sintética da instalação nativa. Não provém do Excel.",
                )
        AuditEvent.objects.create(
            actor=user, action="native.initialized", details={"synthetic": request["synthetic"]}
        )


if __name__ == "__main__":
    main()
