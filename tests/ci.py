"""Surface test identifiers in CI annotations, without settings or private values."""

import unittest

from django.test.runner import DiscoverRunner


class AnnotatedResult(unittest.TextTestResult):
    def addFailure(self, test, error):
        super().addFailure(test, error)
        print("::error::Django test failed: " + test.id(), flush=True)

    def addError(self, test, error):
        super().addError(test, error)
        print("::error::Django test error: " + test.id(), flush=True)

    def addSubTest(self, test, subtest, error):
        super().addSubTest(test, subtest, error)
        if error is not None:
            # Report the parent identifier only: subtest parameters can contain
            # fixture passwords or private values. Never copy them to annotations.
            category = "failed" if issubclass(error[0], test.failureException) else "error"
            print(f"::error::Django subtest {category}: {test.id()}", flush=True)


class AnnotatedTextRunner(unittest.TextTestRunner):
    resultclass = AnnotatedResult


class AnnotatingRunner(DiscoverRunner):
    test_runner = AnnotatedTextRunner
