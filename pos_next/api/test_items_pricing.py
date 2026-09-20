import unittest

from pos_next.api.items import pick_display_price


class TestPickDisplayPrice(unittest.TestCase):
	"""The catalogue tile price is deterministic and never an invented per-unit rate."""

	conversions = {"3 Unité": 3, "Douzaine": 12, "Boite (24)": 24}

	def test_stock_uom_price_wins(self):
		prices = {"Unité": 250, "Douzaine": 2500}
		self.assertEqual(pick_display_price(prices, "Unité", self.conversions), (250, "Unité", 1))

	def test_item_price_without_uom_counts_as_stock_uom(self):
		self.assertEqual(pick_display_price({"": 40}, "Unité", self.conversions), (40, "Unité", 1))
		self.assertEqual(pick_display_price({None: 40}, "Unité", self.conversions), (40, "Unité", 1))

	def test_pack_only_item_shows_the_smallest_pack_in_its_own_uom(self):
		prices = {"Douzaine": 1150, "3 Unité": 300, "Boite (24)": 2200}
		# previously: the alphabetically first UOM ("3 Unité") divided by its factor -> 100 "per Unité"
		self.assertEqual(pick_display_price(prices, "Unité", self.conversions), (300, "3 Unité", 3))

	def test_alphabetical_order_does_not_decide(self):
		prices = {"Boite (24)": 2200, "Douzaine": 1150}
		self.assertEqual(pick_display_price(prices, "Unité", self.conversions), (1150, "Douzaine", 12))

	def test_pack_with_a_conversion_beats_one_without(self):
		prices = {"Caisse": 9000, "Douzaine": 1150}
		self.assertEqual(pick_display_price(prices, "Unité", self.conversions), (1150, "Douzaine", 12))

	def test_price_in_an_unconvertible_uom_is_shown_as_is(self):
		# the item's conversion table does not know "Boite": show the price in that UOM (as before)
		self.assertEqual(pick_display_price({"Boite": 750}, "Boite(100 UNT)", None), (750, "Boite", 1))

	def test_zero_rate_row_counts_as_no_price(self):
		prices = {"Unité": 0, "3 Unité": 850, "Douzaine": 3400}
		self.assertEqual(pick_display_price(prices, "Unité", self.conversions), (850, "3 Unité", 3))

	def test_unpriced_item(self):
		self.assertEqual(pick_display_price({}, "Unité", self.conversions), (0.0, "Unité", 1))
		self.assertEqual(pick_display_price(None, "Unité", None), (0.0, "Unité", 1))
		self.assertEqual(pick_display_price({"Unité": 0}, "Unité", None), (0.0, "Unité", 1))
