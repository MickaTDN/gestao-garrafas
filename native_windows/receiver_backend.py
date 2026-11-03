"""Device-only process, isolated from local HTTP and the administrative Wi-Fi backend."""

import json
import os
from pathlib import Path

import django
from waitress import serve


def main():
    phase = "django_setup"
    try:
        django.setup()
        from native_windows.schema import assert_current

        phase = "schema"
        assert_current()
        from django.conf import settings
        from django.core.wsgi import get_wsgi_application

        phase = "listener"
        serve(
            get_wsgi_application(),
            host="127.0.0.1",
            port=settings.SHEET_RECEIVER["backend_port"],
            clear_untrusted_proxy_headers=False,
            threads=4,
        )
    except Exception as error:
        # No exception text, SQL, PEM, body or connection credentials.
        record = {"phase": phase, "category": type(error).__name__}
        try:
            path = Path(os.environ["GVA_DATA_ROOT"]) / "runtime/receiver/backend.json"
            path.write_text(json.dumps(record))
        except OSError:
            pass
        raise


if __name__ == "__main__":
    main()
