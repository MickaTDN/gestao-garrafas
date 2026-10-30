"""Reject older/incomplete application code even if filesystem metadata was lost."""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from .package import UnsafeOperation


def assert_current():
    executor = MigrationExecutor(connection)
    known = set(executor.loader.disk_migrations)
    applied = set(executor.loader.applied_migrations)
    if applied - known or executor.migration_plan(executor.loader.graph.leaf_nodes()):
        raise UnsafeOperation(
            "Esquema incompatível com esta versão. Arranque recusado; não execute código antigo nem migrações inversas."
        )
