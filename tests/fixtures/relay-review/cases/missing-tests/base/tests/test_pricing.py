import unittest

from shop.pricing import shipping_cost


class ShippingTests(unittest.TestCase):
    def test_flat_rate(self):
        self.assertEqual(shipping_cost(10.0), 4.99)
