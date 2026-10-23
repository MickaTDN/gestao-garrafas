from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections
from django.test import TransactionTestCase, skipUnlessDBFeature

from inventory.models import Location, Movement, MovementLine, Person, Reference
from inventory.services import confirm_movement


class ConcurrentConfirmationTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    def test_two_simultaneous_exits_cannot_oversell(self):
        actor = get_user_model().objects.create_user(username="concorrencia_teste", role="admin")
        location = Location.objects.create(name="Local sintético concorrente")
        reference = Reference.objects.create(code="CONC-001", name="Produto sintético", current_stock=10, location=location)
        person = Person.objects.create(name="Pessoa sintética concorrente")
        movements = [Movement.objects.create(kind="exit", person=person, validation="simple") for _ in range(2)]
        for movement in movements:
            MovementLine.objects.create(movement=movement, reference=reference, quantity=-7)
        barrier = Barrier(2)

        def confirm(movement_id):
            close_old_connections()
            try:
                thread_actor = get_user_model().objects.get(pk=actor.pk)
                barrier.wait(timeout=10)
                try:
                    confirm_movement(movement_id, actor=thread_actor)
                    return "confirmed"
                except ValidationError:
                    return "insufficient"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(confirm, movement.pk) for movement in movements]
            results = [future.result(timeout=15) for future in futures]
        self.assertCountEqual(results, ["confirmed", "insufficient"])
        reference.refresh_from_db()
        self.assertEqual(reference.current_stock, 3)
        self.assertEqual(Movement.objects.filter(status="confirmed").count(), 1)
