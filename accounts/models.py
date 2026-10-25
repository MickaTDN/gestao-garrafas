from django.contrib.auth.models import AbstractUser
from django.db import models


class AccessProfile(models.Model):
    name = models.CharField(max_length=100, unique=True)
    active = models.BooleanField(default=True)
    capabilities = models.JSONField(default=list)

    def __str__(self):
        return self.name


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "Administrador"
        VIEWER = "viewer", "Consulta"
        CUSTOM = "custom", "Personalizado"

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.VIEWER)
    access_profile = models.ForeignKey(AccessProfile, on_delete=models.PROTECT, null=True, blank=True)
    must_change_password = models.BooleanField(default=False, editable=False)

    class Meta:
        constraints = [models.CheckConstraint(
            condition=models.Q(role__in=["admin", "viewer", "custom"]), name="valid_user_role"
        )]

    @property
    def is_administrator(self):
        return self.is_active and self.role == self.Role.ADMIN


class LoginLimit(models.Model):
    """HMAC bucket identifiers; no username, password or address stored here."""
    key = models.CharField(max_length=64, primary_key=True)
    attempts = models.PositiveIntegerField(default=0)
    window_started = models.DateTimeField()
