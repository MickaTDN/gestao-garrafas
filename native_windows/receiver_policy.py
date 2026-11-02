"""Strict origins for approved internal DNS; never interpolate arbitrary URLs into NGINX."""

import re
from urllib.parse import urlsplit

from .package import UnsafeOperation


def origin(value):
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
            or not parsed.hostname
            or not re.fullmatch(
                r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9-]{2,63}", parsed.hostname
            )
            or not 1 <= (parsed.port or 443) <= 65535
            or value != "https://" + parsed.netloc
            or parsed.netloc != parsed.netloc.lower()
        ):
            raise ValueError
        return value
    except (ValueError, TypeError) as error:
        raise UnsafeOperation(
            "Use uma origem HTTPS com DNS interno aprovado, sem caminhos ou credenciais."
        ) from error
