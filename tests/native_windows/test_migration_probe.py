import ast
import shutil
import tempfile
from pathlib import Path
from unittest import TestCase

from django.db.migrations.graph import MigrationGraph

from scripts.native.build_package import ROOT, add_synthetic_migration_probe


class SyntheticMigrationProbeTests(TestCase):
    def test_update_probe_extends_the_real_schema_without_competing_leaves(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory)
            target = app / "consultation/migrations"
            shutil.copytree(ROOT / "consultation/migrations", target)
            add_synthetic_migration_probe(app)
            graph = MigrationGraph()
            dependencies = {}
            for path in target.glob("[0-9]*.py"):
                node = ("consultation", path.stem)
                graph.add_node(node, None)
                tree = ast.parse(path.read_text())
                for assignment in ast.walk(tree):
                    if not isinstance(assignment, ast.Assign) or not any(
                        isinstance(name, ast.Name) and name.id == "dependencies"
                        for name in assignment.targets
                    ):
                        continue
                    dependencies[node] = [
                        ast.literal_eval(item)
                        for item in assignment.value.elts
                        if isinstance(item, ast.Tuple)
                        and ast.literal_eval(item)[0] == "consultation"
                    ]
            for node, parents in dependencies.items():
                for parent in parents:
                    graph.add_dependency(None, node, parent)
            graph.ensure_not_cyclic()
            self.assertEqual(
                graph.leaf_nodes("consultation"),
                [("consultation", "0005_native_synthetic_probe")],
            )
