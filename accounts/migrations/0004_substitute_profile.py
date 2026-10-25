from django.db import migrations
from django.db.migrations.exceptions import IrreversibleError


def seed(apps, schema_editor):
    apps.get_model("accounts", "AccessProfile").objects.get_or_create(
        name="Substituto",
        defaults={"active": True, "capabilities": ["stock_view", "entry", "exit", "reports_view"]},
    )


def protect(apps, schema_editor):
    if apps.get_model("accounts", "User").objects.filter(role="custom").exists():
        raise IrreversibleError(
            "Existem contas com perfis A2. Preserve os dados e use recuperacao compativel, sem remover atribuicoes."
        )
    for profile in apps.get_model("accounts", "AccessProfile").objects.all():
        if (
            profile.name != "Substituto"
            or not profile.active
            or set(profile.capabilities) != {"stock_view", "entry", "exit", "reports_view"}
        ):
            raise IrreversibleError(
                "Existem perfis personalizados. Nao remover configuracoes de acesso; preserve a base A2."
            )


class Migration(migrations.Migration):
    dependencies = [("accounts", "0003_accessprofile_remove_user_valid_user_role_and_more")]
    operations = [migrations.RunPython(seed, protect)]
