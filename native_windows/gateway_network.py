"""Administrative-only cross-gateway conflict checks; no sibling reads at runtime."""

import json
from pathlib import Path

from .package import UnsafeOperation


def validate_gateway_ports(root, config, *, sibling):
    root = Path(root)
    ports = {config["port"], config["backend_port"]}
    for path in (root / "secrets" / sibling / "config.json", root / "publisher.json"):
        if path.is_file():
            saved = json.loads(path.read_text())
            occupied = {saved["port"]}
            if "backend_port" in saved:
                occupied.add(saved["backend_port"])
            if ports & occupied:
                raise UnsafeOperation("Os gateways não podem partilhar portas.")
