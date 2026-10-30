"""Expose synthetic unit failures in CI annotations, even without log access."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests.native_windows.windows_smoke import log  # noqa: E402


class NativeResult(unittest.TextTestResult):
    def annotate(self, test, error):
        message = f"{test.id()}: {error[0].__name__}: {error[1]}"
        escaped = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        log("::error::Native unit test: " + escaped)

    def addError(self, test, error):
        super().addError(test, error)
        self.annotate(test, error)

    def addFailure(self, test, error):
        super().addFailure(test, error)
        self.annotate(test, error)

    def addSubTest(self, test, subtest, error):
        super().addSubTest(test, subtest, error)
        if error is not None:
            self.annotate(subtest, error)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.discover(
        str(ROOT / "tests/native_windows"), top_level_dir=str(ROOT)
    )
    result = unittest.TextTestRunner(verbosity=2, resultclass=NativeResult).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
