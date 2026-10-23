"""Private reports never belong in a checkout or application static directory."""

import json
import os

from django.core.serializers.json import DjangoJSONEncoder

from imports.management.commands.inspect_stock_excel import private_report_path


def write_private_report(destination, data):
    path = private_report_path(destination)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream, cls=DjangoJSONEncoder, ensure_ascii=False, indent=2,
                      allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path
