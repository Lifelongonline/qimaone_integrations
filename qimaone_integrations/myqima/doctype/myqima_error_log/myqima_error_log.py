# Copyright (c) 2026, gopal@8848digital.com and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime, strip_html

BOOKING_JOB = "Inspection Booking"
REPORT_JOB = "Report Fetch"


class MyQimaErrorLog(Document):
	"""A problem the MyQima scheduler hit for one Quality Request, kept open until it is resolved."""


def log_myqima_error(quality_request, job, error):
	"""
	Record an error against a Quality Request, keeping one open log per Quality Request and job.

	A repeat of an open log updates its error, Last Seen and Occurrences instead of adding another,
	so a Quality Request failing on every run does not fill the list. Committed on its own, so it
	survives the rollback of the work that failed.

	Args:
		quality_request (str): name of the Quality Request
		job (str): BOOKING_JOB or REPORT_JOB
		error (str): the error message; HTML is stripped
	"""
	now = now_datetime()
	error = strip_html(str(error).replace("<br>", "\n")).strip()
	quality_request_modified = frappe.db.get_value("Quality Request", quality_request, "modified")

	open_log = get_open_error(quality_request, job)
	if open_log:
		frappe.db.set_value(
			"MyQima Error Log",
			open_log,
			{
				"error": error,
				"last_seen": now,
				"occurrences": (frappe.db.get_value("MyQima Error Log", open_log, "occurrences") or 0) + 1,
				"quality_request_modified": quality_request_modified,
			},
		)
	else:
		frappe.get_doc(
			{
				"doctype": "MyQima Error Log",
				"quality_request": quality_request,
				"job": job,
				"status": "Open",
				"error": error,
				"first_seen": now,
				"last_seen": now,
				"occurrences": 1,
				"quality_request_modified": quality_request_modified,
			}
		).insert(ignore_permissions=True)

	frappe.db.commit()


def resolve_myqima_error(quality_request, job):
	"""Mark the open log of a Quality Request and job Resolved, once the job has succeeded for it."""
	open_log = get_open_error(quality_request, job)
	if open_log:
		frappe.db.set_value("MyQima Error Log", open_log, "status", "Resolved")


def get_open_error(quality_request, job):
	"""Return the name of the open log for a Quality Request and job, or None."""
	return frappe.db.get_value(
		"MyQima Error Log", {"quality_request": quality_request, "job": job, "status": "Open"}
	)


def get_open_error_summaries(quality_request: str) -> list[dict]:
	"""
	Return the open logs of a Quality Request, newest first, for the warning on its form.

	Throws unless the user can read the Quality Request. Only logs the user may read are
	returned, and each carries just the first line of its error, so a traceback stored for an
	unexpected error never reaches the browser.

	Args:
		quality_request (str): name of the Quality Request

	Returns:
		list[dict]: [{"name", "job", "summary", "last_seen", "occurrences"}, ...]
	"""
	frappe.has_permission("Quality Request", "read", doc=quality_request, throw=True)

	logs = frappe.get_list(
		"MyQima Error Log",
		filters={"quality_request": quality_request, "status": "Open"},
		fields=["name", "job", "error", "last_seen", "occurrences"],
		order_by="last_seen desc",
	)
	for log in logs:
		log["summary"] = (log.pop("error") or "").strip().split("\n")[0]

	return logs
