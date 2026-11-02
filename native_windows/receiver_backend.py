"""Device-only process, isolated from local HTTP and the administrative Wi-Fi backend."""

import django
from waitress import serve

django.setup()
from native_windows.schema import assert_current  # noqa: E402

assert_current()
from django.conf import settings  # noqa: E402
from django.core.wsgi import get_wsgi_application  # noqa: E402

serve(
    get_wsgi_application(),
    host="127.0.0.1",
    port=settings.SHEET_RECEIVER["backend_port"],
    clear_untrusted_proxy_headers=False,
    threads=4,
)
