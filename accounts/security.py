import hashlib
import hmac
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import LoginLimit


def bucket_key(namespace, value):
    return hmac.new(
        settings.SECRET_KEY.encode(), f"{namespace}:{value}".encode(), hashlib.sha256
    ).hexdigest()


@transaction.atomic
def reserve_login_attempt(username, address):
    now = timezone.now()
    limits = [
        (bucket_key("user", username.strip().casefold()), settings.LOGIN_ACCOUNT_LIMIT),
        (bucket_key("address", address), settings.LOGIN_ADDRESS_LIMIT),
    ]
    rows = []
    for key, maximum in sorted(limits):
        LoginLimit.objects.get_or_create(key=key, defaults={"window_started": now})
        row = LoginLimit.objects.select_for_update().get(pk=key)
        if row.window_started + timedelta(seconds=settings.LOGIN_WINDOW_SECONDS) <= now:
            row.attempts, row.window_started = 0, now
        rows.append((row, maximum))
    allowed = all(row.attempts < maximum for row, maximum in rows)
    for row, maximum in rows:
        if allowed:
            row.attempts += 1
        row.save(update_fields=["attempts", "window_started"])
    return allowed


def successful_login(username):
    LoginLimit.objects.filter(pk=bucket_key("user", username.strip().casefold())).delete()
