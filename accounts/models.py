from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "Administrador"
        VIEWER = "viewer", "Consulta"

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.VIEWER)

    class Meta:
        constraints = [models.CheckConstraint(
            condition=models.Q(role__in=["admin", "viewer"]), name="valid_user_role"
        )]

    @property
    def is_administrator(self):
        return self.is_active and self.role == self.Role.ADMIN


class LoginLimit(models.Model):
    """HMAC bucket identifiers; no username, password or address stored here."""
    key = models.CharField(max_length=64, primary_key=True)
    attempts = models.PositiveIntegerField(default=0)
    window_started = models.DateTimeField()
