from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.db import close_old_connections
from django.test import TransactionTestCase, override_settings, skipUnlessDBFeature

from accounts.models import LoginLimit
from accounts.security import reserve_login_attempt


@skipUnlessDBFeature("has_select_for_update")
@override_settings(LOGIN_ACCOUNT_LIMIT=3, LOGIN_ADDRESS_LIMIT=10)
class LoginConcurrencyTests(TransactionTestCase):
    def test_concurrent_reservations_cannot_bypass_login_limit(self):
        barrier = Barrier(6)

        def attempt():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return reserve_login_attempt("synthetic-concurrent", "192.0.2.5")
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: attempt(), range(6)))
        self.assertEqual(sum(results), 3)
        self.assertEqual(set(LoginLimit.objects.values_list("attempts", flat=True)), {3})
