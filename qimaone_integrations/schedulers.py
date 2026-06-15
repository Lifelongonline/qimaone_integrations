# Copyright (c) 2026, gopal@8848digital.com and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime

from qimaone_integrations.qimaone_integrations.doctype.qima_settings.api.api import (
	append_draft_inspections_to_csv,
	fetch_inspections,
	product_uploads,
)

# Each scheduled sync is driven by a gate field on Qima Settings:
#   - "hours_field": an Int "no of hours" interval; a run triggers when
#     (now - last_run) >= configured hours.
#   - "enabled_field": a Check; the sync runs every dispatch (hourly) while ticked.
# The last run timestamp is persisted on the settings doc so the interval
# survives restarts.
SYNC_JOBS = [
	{
		"label": "QIMAone PO Sync",
		"hours_field": "no_of_hours",
		"last_run_field": "last_po_sync",
		"function": append_draft_inspections_to_csv,
	},
	{
		"label": "QIMAone Inspection Sync",
		"hours_field": "no_of_hours_for_reports_sync",
		"last_run_field": "last_inspection_sync",
		"function": fetch_inspections,
	},
	{
		"label": "QIMAone Item Sync",
		"enabled_field": "enable_item_sync",
		"last_run_field": "last_item_sync",
		"function": product_uploads,
	},
]


def _is_due(job, settings, now):
	"""Decide whether a sync job should run on this dispatch."""
	enabled_field = job.get("enabled_field")
	if enabled_field:
		# Checkbox-gated: run every dispatch while the box is ticked.
		return bool(frappe.utils.cint(settings.get(enabled_field)))

	hours = frappe.utils.cint(settings.get(job["hours_field"]))
	if hours <= 0:
		# Interval not configured / disabled.
		return False

	last_run = settings.get(job["last_run_field"])
	if last_run and get_datetime(last_run) > add_to_date(now, hours=-hours):
		# Not enough time has elapsed since the last run.
		return False

	return True


def run_scheduled_syncs():
	"""Hourly dispatcher: run each QIMAone sync whose gate condition is met."""
	settings = frappe.get_single("Qima Settings")
	now = now_datetime()

	for job in SYNC_JOBS:
		if not _is_due(job, settings, now):
			continue

		try:
			job["function"]()
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"{job['label']} scheduled run failed")
		finally:
			# Always advance the timestamp so a failing job doesn't retry every hour.
			frappe.db.set_value("Qima Settings", "Qima Settings", job["last_run_field"], now)
