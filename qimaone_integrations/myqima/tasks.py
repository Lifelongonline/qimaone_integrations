# Copyright (c) 2026, gopal@8848digital.com and contributors
# For license information, please see license.txt

"""
MyQima scheduler: auto inspection booking and auto report fetch.

hooks.py runs run_scheduler on every scheduler tick ("all" event, every 4 minutes by default),
which writes no Scheduled Job Log. It reads MyQima Settings once and queues each job on the long
queue whose switch is on and whose interval has passed since its last run; with both switched off
it ends after that one read. The frequency is therefore set from the MyQima Settings form, in
steps of the scheduler tick.

The queued job has a fixed job ID, so a new run is never queued while the previous one is still
waiting or running. A run stops starting new Quality Requests after RUN_TIME_BUDGET, so it hands
the long worker back to other apps, and the next run carries on. The report fetch carries on after
the last Quality Request it checked, so every open booking gets its turn however many there are.
Each Quality Request is worked on holding its myqima_lock, shared with the form buttons, so the
scheduler and a user never book or fetch the same one at once.

Errors go to MyQima Error Log, one open log per Quality Request and job, never to Error Log.
"""

import time

import frappe
from frappe.utils import add_to_date, cint, get_datetime, now_datetime
from frappe.utils.background_jobs import is_job_enqueued

from qimaone_integrations.myqima.customizations.quality_request.quality_request import (
	book_quality_request,
	fetch_quality_request_reports,
)
from qimaone_integrations.myqima.doctype.myqima_error_log.myqima_error_log import (
	BOOKING_JOB,
	REPORT_JOB,
	log_myqima_error,
)
from qimaone_integrations.myqima.utils import MyQimaBusyError, myqima_lock

# Quality Requests worked on per run at most; the rest follow on the next runs
BATCH_SIZE = 50

# No new Quality Request is started once RUN_TIME_BUDGET seconds have passed, so a run holds a long
# worker for a few minutes at most. The long queue stops a job after JOB_TIMEOUT seconds, which
# leaves room for the one in progress: a booking takes at most about 70 seconds (token refresh or
# login, then the booking call), so a job is never stopped between QIMA creating an order and the
# order being saved here, which would book it twice.
RUN_TIME_BUDGET = 300
JOB_TIMEOUT = 900

BOOKING_METHOD = "qimaone_integrations.myqima.tasks.book_pending_quality_requests"
REPORT_METHOD = "qimaone_integrations.myqima.tasks.fetch_pending_reports"

# Cache key of the last Quality Request the report fetch checked, as [posting_date, name]
REPORT_CURSOR_KEY = "myqima_report_fetch_cursor"


def run_scheduler():
	"""Scheduler tick: queue the auto booking and the auto report fetch when each is due."""
	values = frappe.db.get_singles_dict("MyQima Settings")
	if not values.get("sync_from_date"):
		return

	_dispatch(values, "enable_auto_booking", "booking_interval", "last_booking_run", BOOKING_METHOD)
	_dispatch(
		values, "enable_auto_report_fetch", "report_fetch_interval", "last_report_fetch_run", REPORT_METHOD
	)


def book_pending_quality_requests(from_date):
	"""
	Queued job: book each Quality Request picked by get_quality_requests_to_book.

	Args:
		from_date (str): Sync From Date of MyQima Settings
	"""
	_run_batch(BOOKING_JOB, get_quality_requests_to_book, book_quality_request, from_date)


def fetch_pending_reports(from_date):
	"""
	Queued job: fetch the reports of the next Quality Requests with a report pending.

	The Quality Requests are picked by get_next_report_batch. After each one, it is saved as the
	place the next run carries on from.

	Args:
		from_date (str): Sync From Date of MyQima Settings
	"""
	_run_batch(
		REPORT_JOB,
		get_next_report_batch,
		fetch_quality_request_reports,
		from_date,
		on_done=lambda row: frappe.cache.set_value(REPORT_CURSOR_KEY, [row.posting_date, row.name]),
	)


def get_next_report_batch(from_date):
	"""
	Return the next Quality Requests with a report pending, after the last one checked.

	Bookings QIMA has not inspected yet, pending decisions and reports that could not be applied
	all stay pending, so always taking the oldest would check the same ones on every run and never
	reach the newer ones. The batch therefore carries on after the last Quality Request checked,
	and wraps round to the oldest at the end.
	"""
	cursor = frappe.cache.get_value(REPORT_CURSOR_KEY)
	rows = get_quality_requests_with_pending_reports(from_date, after=cursor)
	if not cursor or len(rows) == BATCH_SIZE:
		return rows

	taken = {row.name for row in rows}
	from_start = get_quality_requests_with_pending_reports(from_date)
	return rows + [row for row in from_start if row.name not in taken][: BATCH_SIZE - len(rows)]


def get_quality_requests_to_book(from_date):
	"""
	Return the Quality Requests the auto booking should book, oldest first, at most BATCH_SIZE.

	A Quality Request is picked when it is submitted, posted on or after from_date, has an
	inspection for an import supplier whose item is in an Item Group allowed in MyQima Settings,
	and none of its inspections has ever been booked. One with no such row is not a MyQima
	request, so it is skipped without an error log. One whose booking was cancelled is never
	booked again. One with an open booking error log is skipped until the Quality Request is
	modified after the error, or the log is resolved.

	Returns:
		list[frappe._dict]: name and posting_date of each Quality Request
	"""
	return frappe.db.sql(
		"""
		select qr.name, qr.posting_date
		from `tabQuality Request` qr
		where qr.docstatus = 1
			and qr.posting_date >= %(from_date)s
			and exists (
				select 1 from `tabQuality Request Item` qri
				join `tabQuality Inspection` qi on qi.name = qri.quality_inspection
				join `tabItem` item on item.name = qri.item_code
				join `tabQIMA Allowed Item Group` allowed
					on allowed.item_group = item.item_group
					and allowed.parenttype = 'MyQima Settings'
					and allowed.parentfield = 'myqima_allowed_item_group'
				where qri.parent = qr.name and qi.custom_import_supplier = 1 and qi.docstatus < 2
			)
			and not exists (
				select 1 from `tabQuality Request Item` qri
				join `tabMyQima Details` md
					on md.parent = qri.quality_inspection
					and md.parenttype = 'Quality Inspection'
					and md.parentfield = 'custom_myqima_details'
				where qri.parent = qr.name and ifnull(md.myqima_booking_id, '') != ''
			)
			and not exists (
				select 1 from `tabMyQima Error Log` log
				where log.quality_request = qr.name
					and log.job = %(job)s
					and log.status = 'Open'
					and log.quality_request_modified >= qr.modified
			)
		order by qr.posting_date, qr.name
		limit %(limit)s
		""",
		{"from_date": from_date, "job": BOOKING_JOB, "limit": BATCH_SIZE},
		as_dict=True,
	)


def get_quality_requests_with_pending_reports(from_date, after=None):
	"""
	Return the Quality Requests with a report to fetch, oldest first, at most BATCH_SIZE.

	A Quality Request is picked when it is submitted, posted on or after from_date, and one of
	its import-supplier inspections has an active (not cancelled) booking whose report is not
	fetched yet, was fetched with its report decision pending, or could not be applied to the
	inspection. Failing ones are retried every run: an order finishes on QIMA's side, and a
	report that could not be applied may have been fixed here, so there is nothing to wait for.

	Args:
		from_date (str): Sync From Date of MyQima Settings
		after (list): [posting_date, name] of a Quality Request; only later ones are returned

	Returns:
		list[frappe._dict]: name and posting_date of each Quality Request
	"""
	values = {"from_date": from_date, "limit": BATCH_SIZE}
	after_condition = ""
	if after:
		values.update(after_date=after[0], after_name=after[1])
		after_condition = """and (
			qr.posting_date > %(after_date)s
			or (qr.posting_date = %(after_date)s and qr.name > %(after_name)s)
		)"""

	return frappe.db.sql(
		f"""
		select distinct qr.name, qr.posting_date
		from `tabQuality Request` qr
		join `tabQuality Request Item` qri on qri.parent = qr.name
		join `tabQuality Inspection` qi on qi.name = qri.quality_inspection
		join `tabMyQima Details` md
			on md.parent = qi.name
			and md.parenttype = 'Quality Inspection'
			and md.parentfield = 'custom_myqima_details'
		where qr.docstatus = 1
			and qr.posting_date >= %(from_date)s
			and qi.custom_import_supplier = 1
			and qi.docstatus < 2
			and ifnull(md.myqima_booking_id, '') != ''
			and md.myqima_booking_cancelled = 0
			and (
				md.myqima_report_fetched = 0
				or md.myqima_decision_pending = 1
				or md.myqima_report_not_applied = 1
			)
			{after_condition}
		order by qr.posting_date, qr.name
		limit %(limit)s
		""",
		values,
		as_dict=True,
	)


def _dispatch(values, enabled_field, interval_field, last_run_field, method):
	"""
	Queue method(from_date) on the long queue when the job is enabled and its interval has passed.

	Nothing is queued while the previous run is still waiting or running. The last run is saved
	when the job is queued, so a run that fails still waits a full interval before the next one.

	Args:
		values (dict): MyQima Settings, as read once per scheduler tick
	"""
	if not cint(values.get(enabled_field)):
		return

	now = now_datetime()
	interval = max(cint(values.get(interval_field)), 1)
	last_run = values.get(last_run_field)
	if last_run and get_datetime(last_run) > add_to_date(now, minutes=-interval):
		return

	if is_job_enqueued(method):
		return

	frappe.db.set_single_value("MyQima Settings", last_run_field, now)
	frappe.db.commit()

	frappe.enqueue(
		method,
		queue="long",
		timeout=JOB_TIMEOUT,
		job_id=method,
		deduplicate=True,
		from_date=values.get("sync_from_date"),
	)


def _run_batch(job, get_quality_requests, work, from_date, on_done=None):
	"""
	Run work for each Quality Request picked by get_quality_requests, until RUN_TIME_BUDGET is spent.

	Never raises: a failure for one Quality Request is logged against it by _process, and a failure
	to list them goes to the myqima log file, so nothing from these jobs lands in Error Log.

	Args:
		on_done (callable): called with each Quality Request's row once it is worked on or skipped
	"""
	started = time.monotonic()
	try:
		rows = get_quality_requests(from_date)
	except Exception:
		frappe.logger("myqima").exception(f"[MyQima] {job}: could not list the Quality Requests")
		return

	for row in rows:
		if time.monotonic() - started > RUN_TIME_BUDGET:
			break
		_process(row.name, job, work)
		if on_done:
			on_done(row)


def _process(quality_request, job, work):
	"""
	Run work(doc) for one Quality Request holding its lock, logging any error against it.

	A Quality Request locked by a user or another worker is skipped for this run. An error rolls
	its work back and is kept in MyQima Error Log; the other Quality Requests carry on. The first
	line of the log is always a one-line summary, followed by the traceback for unexpected errors.
	"""
	try:
		with myqima_lock(quality_request):
			work(frappe.get_doc("Quality Request", quality_request))
		frappe.db.commit()
	except MyQimaBusyError:
		return
	except Exception as exc:
		frappe.db.rollback()
		if isinstance(exc, frappe.ValidationError):
			message = str(exc)
		else:
			message = f"{type(exc).__name__}: {exc}\n\n{frappe.get_traceback()}"
		log_myqima_error(quality_request, job, message)
	finally:
		# Messages thrown for one Quality Request must not pile up across the run
		frappe.local.message_log = []
