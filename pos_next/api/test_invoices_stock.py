# Copyright (c) 2026, BrainWise and contributors
# For license information, please see license.txt

"""Unit tests for POS invoice stock validation: aggregation keys and the block decision."""

from __future__ import annotations

import inspect
import unittest
from unittest.mock import MagicMock, patch

from pos_next.api import invoices
from pos_next.api.invoices import _collect_stock_errors


def _row(item_code, warehouse, qty, batch_no="", **extra):
	return {
		"item_code": item_code,
		"warehouse": warehouse,
		"qty": qty,
		"conversion_factor": 1,
		"batch_no": batch_no,
		**extra,
	}


class TestCollectStockErrorsBatchKey(unittest.TestCase):
	@patch("pos_next.api.invoices._get_item_negative_stock_allow_set", return_value=set())
	@patch("pos_next.api.invoices._get_available_stock")
	def test_does_not_oversell_by_checking_wrong_batch(self, mock_avail, _mock_allow):
		"""Demand on BATCH-A must not be validated against BATCH-B stock.

		Regression: aggregating only by (item_code, warehouse) summed both
		rows and compared the total to whichever sample row was last — often
		the larger batch — which allowed overselling the smaller batch.
		"""

		def avail(item):
			return {"BATCH-A": 3.0, "BATCH-B": 10.0}.get(item.get("batch_no") or "", 0.0)

		mock_avail.side_effect = avail

		errors = _collect_stock_errors(
			[
				_row("SKU-1", "Stores - X", 5, "BATCH-A"),
				_row("SKU-1", "Stores - X", 5, "BATCH-B"),
			]
		)

		self.assertEqual(len(errors), 1)
		self.assertEqual(errors[0]["item_code"], "SKU-1")
		self.assertEqual(errors[0]["batch_no"], "BATCH-A")
		self.assertEqual(errors[0]["requested_qty"], 5.0)
		self.assertEqual(errors[0]["available_qty"], 3.0)

	@patch("pos_next.api.invoices._get_item_negative_stock_allow_set", return_value=set())
	@patch("pos_next.api.invoices._get_available_stock")
	def test_same_batch_paid_and_free_rows_are_summed(self, mock_avail, _mock_allow):
		mock_avail.return_value = 3.0

		errors = _collect_stock_errors(
			[
				_row("SKU-1", "Stores - X", 2, "BATCH-A"),
				_row("SKU-1", "Stores - X", 2, "BATCH-A", is_free_item=1),
			]
		)

		self.assertEqual(len(errors), 1)
		self.assertEqual(errors[0]["batch_no"], "BATCH-A")
		self.assertEqual(errors[0]["requested_qty"], 4.0)
		self.assertEqual(errors[0]["available_qty"], 3.0)

	@patch("pos_next.api.invoices._get_item_negative_stock_allow_set", return_value=set())
	@patch("pos_next.api.invoices._get_available_stock")
	def test_non_batch_rows_still_aggregate_by_item_and_warehouse(self, mock_avail, _mock_allow):
		mock_avail.return_value = 5.0

		errors = _collect_stock_errors(
			[
				_row("SKU-1", "Stores - X", 3),
				_row("SKU-1", "Stores - X", 1, is_free_item=1),
			]
		)

		self.assertEqual(errors, [])
		mock_avail.assert_called_once()

		errors_over = _collect_stock_errors(
			[
				_row("SKU-1", "Stores - X", 4),
				_row("SKU-1", "Stores - X", 2, is_free_item=1),
			]
		)
		self.assertEqual(len(errors_over), 1)
		self.assertNotIn("batch_no", errors_over[0])
		self.assertEqual(errors_over[0]["requested_qty"], 6.0)


class TestShouldBlock(unittest.TestCase):
	"""The company decides in Stock Settings; a till can only opt in to that decision."""

	def setUp(self):
		# frappe.db is a site-bound proxy; outside a request it must be replaced whole
		self.db = MagicMock()
		patcher = patch.object(invoices.frappe, "db", self.db)
		patcher.start()
		self.addCleanup(patcher.stop)

	def given(self, company_allows, till_opted_in=0, legacy_block=1):
		self.db.get_single_value.return_value = company_allows

		def get_value(doctype, filters, fieldname=None, *args, **kwargs):
			if doctype == "POS Settings":
				self.assertEqual(filters.get("enabled"), 1, "a disabled settings row must not opt in")
				return till_opted_in
			if doctype == "POS Profile":
				return legacy_block
			return None

		self.db.get_value.side_effect = get_value

	def test_company_off_blocks_even_when_the_till_opted_in(self):
		self.given(company_allows=0, till_opted_in=1)
		self.assertTrue(invoices._should_block("Till"))

	def test_company_on_and_till_opted_in_sells_past_zero(self):
		self.given(company_allows=1, till_opted_in=1)
		self.assertFalse(invoices._should_block("Till"))

	def test_company_on_but_till_not_opted_in_keeps_blocking(self):
		self.given(company_allows=1, till_opted_in=0)
		self.assertTrue(invoices._should_block("Till"))

	def test_cleared_legacy_profile_flag_lets_a_non_opted_till_through(self):
		self.given(company_allows=1, till_opted_in=0, legacy_block=0)
		self.assertFalse(invoices._should_block("Till"))

	def test_missing_legacy_profile_flag_blocks(self):
		self.given(company_allows=1, till_opted_in=0, legacy_block=None)
		self.assertTrue(invoices._should_block("Till"))

	def test_no_profile_blocks(self):
		self.given(company_allows=1)
		self.assertTrue(invoices._should_block(None))


class TestPOSSettingsNeverWritesStockSettings(unittest.TestCase):
	"""Saving a till's settings must leave the company-wide permission alone."""

	def test_no_write_through(self):
		from pos_next.pos_next.doctype.pos_settings import pos_settings as module

		self.assertNotIn("on_update", module.POSSettings.__dict__)
		self.assertFalse(hasattr(module.POSSettings, "sync_negative_stock_setting"))
		self.assertNotIn("set_single_value", inspect.getsource(module))

	def test_settings_carry_the_company_permission(self):
		from pos_next.pos_next.doctype.pos_settings import pos_settings as module

		db = MagicMock()
		db.get_single_value.return_value = 1
		with patch.object(module.frappe, "db", db):
			settings = module.with_global_negative_stock_flag({"allow_negative_stock": 1})
		self.assertEqual(settings["_global_allow_negative_stock"], 1)
		db.get_single_value.assert_called_once_with("Stock Settings", "allow_negative_stock")
