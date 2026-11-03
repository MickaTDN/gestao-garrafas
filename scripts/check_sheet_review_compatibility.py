"""Verify the real integration preserves both reviewed histories and their join."""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "a537f2981798aa17098bee1c01c9c45008efadbe": ["0005_wifi_receipt_actor"],
    "4fd188146a87ca17be4a310f4e1280d218ff9fac": ["0005_sheetaction", "0006_sheet_action_guards"],
}


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def main():
    if git("rev-parse", "--is-shallow-repository").strip() == b"true":
        git("fetch", "--unshallow", "--no-tags", "origin")
    for revision, names in SOURCES.items():
        git("merge-base", "--is-ancestor", revision, "HEAD")
        for name in names:
            path = "consultation/migrations/" + name + ".py"
            if git("show", revision + ":" + path) != (ROOT / path).read_bytes():
                raise RuntimeError("Published migration changed: " + name)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from django.db.migrations.loader import MigrationLoader

    loader = MigrationLoader(None)
    join = ("consultation", "0007_merge_review_wifi")
    expected = {
        ("consultation", "0005_wifi_receipt_actor"),
        ("consultation", "0006_sheet_action_guards"),
    }
    migration = loader.disk_migrations[join]
    if set(migration.dependencies) != expected or migration.operations:
        raise RuntimeError("The join must preserve both parents without data operations")
    leaves = loader.graph.leaf_nodes("consultation")
    if len(leaves) != 1 or not expected | {join} <= set(loader.graph.forwards_plan(leaves[0])):
        raise RuntimeError("Competing or incomplete consultation migration history")
    print(
        "PASS: both exact source commits retained; published migrations unchanged; single joined migration history."
    )


if __name__ == "__main__":
    main()
