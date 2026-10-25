from django.test import SimpleTestCase

from inventory.presentation import entered_quantity, stock_quantity


class QuantityPresentationTests(SimpleTestCase):
    def test_stock_breakdown_omits_zero_components_and_never_invents_capacity(self):
        for quantity, capacity, expected in (
            (15, 6, "2 caixas + 3 garrafas"),
            (6, 6, "1 caixa"),
            (4, 6, "4 garrafas"),
            (1, None, "1 garrafa"),
            (15, None, "15 garrafas"),
            (0, 6, "0 garrafas"),
            (0, None, "0 garrafas"),
            (None, 6, "—"),
        ):
            with self.subTest(quantity=quantity, capacity=capacity):
                self.assertEqual(stock_quantity(quantity, capacity), expected)

    def test_actual_noncanonical_inputs_preserved_and_missing_inputs_fall_back(self):
        self.assertEqual(entered_quantity(1, 8, 14, 6), "1 caixa + 8 garrafas")
        self.assertEqual(entered_quantity(None, 14, 14, 6), "14 garrafas")
        self.assertEqual(entered_quantity(0, 2, -2, 6), "2 garrafas")
        self.assertEqual(entered_quantity(None, None, -14, 6), "2 caixas + 2 garrafas")
        self.assertEqual(entered_quantity(0, 0, 0, None), "0 garrafas")
