# Copyright (c) 2026, gopal@8848digital.com and contributors
# For license information, please see license.txt

from datetime import datetime

import frappe
from frappe.model.document import Document

from qimaone_integrations.myqima.utils import request_token, to_md5_password


class MyQimaSettings(Document):
	def validate(self):
		"""Log new or changed Category Credentials in to MyQima and check the intervals and SKU limit."""
		self.connect_category_credentials()
		self.validate_scheduler_intervals()
		self.validate_sku_limit()

	def validate_sku_limit(self):
		"""Require a limit of at least one SKU when Quality Requests are validated against it."""
		if self.validate_sku_qty_for_qr_creation and (self.no_of_sku_per_quality_request or 0) < 1:
			frappe.throw(f"{self.meta.get_label('no_of_sku_per_quality_request')} must be at least 1.")

	def validate_scheduler_intervals(self):
		"""Require an interval of at least one minute for each scheduler job that is enabled."""
		for enabled_field, interval_field in (
			("enable_auto_booking", "booking_interval"),
			("enable_auto_report_fetch", "report_fetch_interval"),
		):
			if self.get(enabled_field) and (self.get(interval_field) or 0) < 1:
				frappe.throw(f"{self.meta.get_label(interval_field)} must be at least 1 minute.")

	def connect_category_credentials(self):
		"""
		Log each new or changed Category Credentials row in to MyQima and fill in what it returns.

		The user enters only the login and their normal password. The password is stored as the
		MD5 hash MyQima expects, and User ID, access token, refresh key and expiry come from the
		login response. A wrong login stops the save. Rows whose login and password are unchanged
		are not logged in again.
		"""
		before = self.get_doc_before_save()
		saved_accounts = (
			{row.name: row.account for row in before.myqima_category_credentials} if before else {}
		)

		for row in self.myqima_category_credentials:
			password_changed = bool(row.password) and not row.is_dummy_password(row.password)
			if not password_changed and saved_accounts.get(row.name) == row.account:
				continue

			if not row.account:
				frappe.throw(f"Row {row.idx}: please enter the MyQima Login.")

			if password_changed:
				row.password = to_md5_password(row.password)
				password_hash = row.password
			else:
				password_hash = row.get_password("password", raise_exception=False)

			if not password_hash:
				frappe.throw(f"Row {row.idx}: please enter the MyQima Password for <b>{row.account}</b>.")

			content = request_token(self, row.account, password_hash)
			token = content["token"]

			row.userid = (content.get("user") or {}).get("id") or token.get("userId")
			row.access_token = token.get("token")
			row.refresh_key = token.get("refreshKey")
			row.token_expiry = datetime.fromtimestamp(int(token.get("validBefore")))
