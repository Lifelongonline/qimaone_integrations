# Copyright (c) 2026, gopal@8848digital.com and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.query_builder import Interval
from frappe.query_builder.functions import Now


class MyQimaAPILog(Document):
	@staticmethod
	def clear_old_logs(days=90):
		"""Delete logs older than `days`; called by Log Settings."""
		table = frappe.qb.DocType("MyQima API Log")
		frappe.db.delete(table, filters=(table.creation < (Now() - Interval(days=days))))
