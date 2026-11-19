import re
from datetime import date, datetime, timedelta

import frappe
import requests
from frappe.utils import flt

from qimaone_integrations.myqima.utils import (
	MyQimaReportUpdateError,
	call_myqima_api,
	can_bypass_booking_check,
	get_category_credentials,
	get_headers,
	get_valid_token,
	myqima_lock,
)

# What a MyQima report value means for the inspection. None means "no verdict yet" —
# the inspection is left exactly as it is.
#
# Only "Pending" is confirmed against live data; the other decisions are the expected
# wording and are matched case insensitively. A value missing from these maps is
# reported as an error rather than guessed at, and the report is fetched again until
# the value is added here, so the real list can be filled in from production.
OVERALL_RESULT_VERDICTS = {
	"pass": "Accepted",
	"fail": "Rejected",
}

REPORT_DECISION_VERDICTS = {
	"pending": None,
	"approved": "Accepted",
	"accepted": "Accepted",
	"rejected": "Rejected",
	"refused": "Rejected",
}

VERDICT_SOURCES = {
	"MyQima Overall Result": OVERALL_RESULT_VERDICTS,
	"MyQima Report Decision": REPORT_DECISION_VERDICTS,
}

# Report decisions meaning nobody has decided on MyQima yet. While the result is based on the
# report decision, such a report is fetched again until it is decided.
PENDING_REPORT_DECISIONS = {"", "pending"}

# Label of the report's productDetails entry holding the produced quantity, e.g. "55 Pcs"
PRODUCED_QTY_LABEL = "REPORTS.INTERACTIVE_REPORT.PRODUCED_QUANTITY"

# What a consolidated booking's result is always based on, whatever MyQima Settings says:
# MyQima decides each of its SKUs, while its Overall Result covers all of them together
CONSOLIDATED_RESULT_SOURCE = "MyQima Report Decision"


def get_inspection_verdict(settings, overall_result, report_decision, source=None):
	"""Translate a MyQima report into a Quality Inspection status.

	The result is based on source, by default MyQima Settings' Update Result Based On. Returns
	None to mean "leave the inspection alone" — because the setting is off, or because the
	chosen source is still undecided.

	Raises:
		MyQimaReportUpdateError: when the value is one we do not recognise
	"""
	if not settings.auto_update_inspection_result:
		return None

	source = source or settings.update_result_based_on
	verdicts = VERDICT_SOURCES.get(source)
	if not verdicts:
		return None

	value = overall_result if source == "MyQima Overall Result" else report_decision
	if not value:
		return None

	key = value.strip().lower()
	if key not in verdicts:
		raise MyQimaReportUpdateError(
			f"MyQima returned {source} <b>{value}</b>, which is not mapped to an inspection status "
			f"(known values: {', '.join(sorted(verdicts))})."
		)

	return verdicts[key]


def is_decision_pending(settings, report_decision, source=None):
	"""Return True when the inspection's result is based on a MyQima report decision not made yet.

	The result is based on source, by default MyQima Settings' Update Result Based On. Such a
	report maps nothing on the inspection and is fetched again until it is decided.
	"""
	return (
		bool(settings.auto_update_inspection_result)
		and (source or settings.update_result_based_on) == "MyQima Report Decision"
		and (report_decision or "").strip().lower() in PENDING_REPORT_DECISIONS
	)


def get_report_values(doc, report_data):
	"""
	Return what the inspection takes from its MyQima report.

	The order level decision and the produced quantity are the inspection's own, unless it was
	booked consolidated: MyQima then decides each SKU under reportDecision.productReference,
	matched to the inspection on referencePoNumber, which carries the inspection name. Its
	decision and reason are taken from there, its booked referenceQuantity stands in for the
	produced quantity, which the report gives only for all SKUs together, and its result is
	based on CONSOLIDATED_RESULT_SOURCE.

	Returns:
		frappe._dict: overall_result, report_decision, decision_reason, produced_qty, source (None
			to follow MyQima Settings), and found, False when a consolidated report has no
			decision for the inspection
	"""
	decision = report_data.get("reportDecision") or {}
	values = frappe._dict(
		overall_result=(report_data.get("overallResult") or {}).get("overallResult", ""),
		report_decision=decision.get("decision") or "",
		decision_reason=_format_decision_reasons(decision.get("decisionReasons")),
		produced_qty=get_produced_qty(report_data),
		source=None,
		found=True,
	)
	if not is_consolidated(doc):
		return values

	reference = next(
		(ref for ref in decision.get("productReference") or [] if ref.get("referencePoNumber") == doc.name),
		None,
	)
	reference_qty = (reference or {}).get("referenceQuantity")

	values.update(
		report_decision=(reference or {}).get("decision") or "",
		decision_reason=_format_decision_reasons((reference or {}).get("decisionReasons")),
		produced_qty=None if reference_qty is None else flt(reference_qty),
		source=CONSOLIDATED_RESULT_SOURCE,
		found=bool(reference),
	)
	return values


def _format_decision_reasons(reasons):
	"""Return MyQima's decision reasons as text; they come as text, a list of text, or None."""
	if isinstance(reasons, list):
		return ", ".join(str(reason) for reason in reasons if reason)
	return reasons or ""


def apply_report_outcome(doc, settings, verdict):
	"""Update the inspection's status from the verdict of its MyQima report.

	The verdict sets the status; quality_inspection_status then decides whether the
	inspection is submitted. Only an accepted inspection is ever submitted — a
	rejection is left in draft for someone to look at. An inspection no longer in
	draft, e.g. submitted by hand while its report decision was pending, is left alone.

	Raises:
		MyQimaReportUpdateError: when the submit fails; its changes are rolled back and the
			status set before it is kept
	"""
	if not verdict:
		frappe.logger().info(f"[QIMA] {doc.name} left untouched — no verdict from the MyQima report.")
		return

	if doc.docstatus != 0:
		frappe.logger().info(f"[QIMA] {doc.name} left untouched — it is no longer a draft.")
		return

	frappe.db.set_value("Quality Inspection", doc.name, "status", verdict, update_modified=False)
	frappe.db.commit()

	if verdict != "Accepted" or settings.quality_inspection_status != "Submitted":
		doc.reload()
		frappe.logger().info(f"[QIMA] Quality Inspection {doc.name} left as Draft — status {verdict}.")
		return

	frappe.db.savepoint("myqima_submit")
	try:
		doc.reload()
		doc.submit()
	except Exception as exc:
		frappe.db.rollback(save_point="myqima_submit")
		raise MyQimaReportUpdateError(
			f"Status set to {verdict}, but it could not be submitted: {exc}"
		) from exc

	frappe.logger().info(f"[QIMA] Quality Inspection {doc.name} submitted successfully.")


def get_produced_qty(report_data):
	"""Return the produced quantity of a MyQima report, e.g. 55 for "55 Pcs", or None if it has none."""
	for info in (report_data.get("productDetails") or {}).get("generalInfo") or []:
		if info.get("label") != PRODUCED_QTY_LABEL:
			continue

		match = re.match(r"[\d,.]+", str(info.get("value") or "").strip())
		return flt(match.group().replace(",", "")) if match else None

	return None


def get_produced_qty_field(settings, verdict, source=None):
	"""Return the inspection field the report's produced quantity goes to, or None to leave the quantities alone.

	An accepted report's produced quantity is the Accepted Qty (remaining_qty). A rejected one's is
	the Rejected Qty, but only when the result is based on the MyQima Report Decision (source, by
	default MyQima Settings' Update Result Based On); a failed Overall Result leaves the quantities
	to be entered by hand.
	"""
	if verdict == "Accepted":
		return "remaining_qty"
	if verdict == "Rejected" and (source or settings.update_result_based_on) == "MyQima Report Decision":
		return "rejected_qty"
	return None


def apply_produced_qty(doc, settings, verdict, produced_qty, source=None):
	"""Set the inspection's Accepted or Rejected Qty, as the verdict says, to the produced quantity of its MyQima report.

	Offered Qty must stay Accepted Qty + Rejected Qty, which the inspection's validate recomputes
	from Rejected Qty on every save, so the other quantity is set alongside to keep the value. See
	get_produced_qty_field for which verdict sets which quantity. Nothing changes either when the
	report has no produced quantity, or the inspection is no longer a draft.

	Raises:
		MyQimaReportUpdateError: when the quantity exceeds Offered Qty, before anything is set
	"""
	field = get_produced_qty_field(settings, verdict, source)
	if not field or produced_qty is None or doc.docstatus != 0:
		return

	offered_qty = flt(doc.get("custom_offered_qty"))
	if produced_qty > offered_qty:
		raise MyQimaReportUpdateError(
			f"MyQima reports a produced quantity of {produced_qty}, above its Offered Qty of "
			f"{offered_qty}. Please correct the Offered Qty; nothing was changed on the inspection."
		)

	other_field = "rejected_qty" if field == "remaining_qty" else "remaining_qty"
	frappe.db.set_value(
		"Quality Inspection",
		doc.name,
		{field: produced_qty, other_field: offered_qty - produced_qty},
		update_modified=False,
	)
	frappe.db.commit()


def _get_myqima_row(doc):
	"""Return the single MyQima Details child row for this doc, or None if not created yet."""
	if doc.get("custom_myqima_details"):
		return doc.custom_myqima_details[0]
	return None


def _get_myqima_value(doc, fieldname, default=""):
	"""Read a value off the single MyQima Details child row (falls back to default)."""
	row = _get_myqima_row(doc)
	if not row:
		return default
	return row.get(fieldname) or default


def _ensure_myqima_row(doc):
	"""Return the single MyQima Details child row, inserting an empty one first if missing."""
	row = _get_myqima_row(doc)
	if row:
		return row

	new_row = frappe.get_doc(
		{
			"doctype": "MyQima Details",
			"parent": doc.name,
			"parentfield": "custom_myqima_details",
			"parenttype": "Quality Inspection",
			"idx": 1,
		}
	)
	new_row.insert(ignore_permissions=True)

	doc.reload()
	return doc.custom_myqima_details[0]


def _set_myqima_values(doc, values):
	"""Overwrite fields on the single MyQima Details child row (creating it if needed)."""
	row = _ensure_myqima_row(doc)
	frappe.db.set_value("MyQima Details", row.name, values, update_modified=False)


def has_active_booking(doc):
	"""Return True when the inspection carries a MyQima booking that has not been cancelled."""
	return bool(_get_myqima_value(doc, "myqima_booking_id")) and not _get_myqima_value(
		doc, "myqima_booking_cancelled"
	)


def is_consolidated(doc):
	"""
	Return True when the inspection was booked with Push Consolidated Items in MyQima Portal.

	Inspections booked consolidated before MyQima Consolidated was stored are known by sharing
	their product with another inspection.
	"""
	return bool(_get_myqima_value(doc, "myqima_consolidated")) or is_shared_product(doc)


def is_shared_product(doc):
	"""Return True when another inspection's active booking shares this MyQima product, as when consolidated."""
	product_id = _get_myqima_value(doc, "myqima_product_id")
	return bool(product_id) and bool(
		frappe.db.exists(
			"MyQima Details",
			{
				"parenttype": "Quality Inspection",
				"parent": ["!=", doc.name],
				"myqima_product_id": product_id,
				"myqima_booking_cancelled": 0,
			},
		)
	)


def is_report_due(doc):
	"""Return True when the inspection's report is to be fetched: never fetched, fetched before its decision, or not applied."""
	return (
		not _get_myqima_value(doc, "myqima_report_fetched")
		or bool(_get_myqima_value(doc, "myqima_decision_pending"))
		or bool(_get_myqima_value(doc, "myqima_report_not_applied"))
	)


def throw_report_update_errors(failed):
	"""
	Throw one error listing the inspections whose MyQima report could not be applied, if any.

	The first line is a one-line summary, shown on the Quality Request for a scheduler error.

	Args:
		failed (list[str]): one "<inspection>: <reason>" line per inspection
	"""
	if not failed:
		return

	frappe.throw(
		f"The MyQima report could not be applied to {len(failed)} Quality Inspection(s) "
		f"and is fetched again until it applies.<br><br>" + "<br>".join(failed),
		exc=MyQimaReportUpdateError,
		title="MyQima Report Not Applied",
	)


def before_cancel(doc, method=None):
	"""Refuse to cancel an inspection whose MyQima booking is still active.

	A cancelled booking keeps its details on the inspection with MyQima Booking Cancelled
	checked, which lets the inspection be cancelled. Users with BOOKING_CANCEL_BYPASS_ROLE
	skip this check.
	"""
	if not has_active_booking(doc) or can_bypass_booking_check():
		return

	order = _get_myqima_value(doc, "myqima_order_number") or _get_myqima_value(doc, "myqima_booking_id")
	if doc.get("custom_quality_request"):
		where = (
			f"from Quality Request <b>{doc.custom_quality_request}</b> "
			f"(MYQIMA &gt; Cancel MYQIMA Inspection)"
		)
	else:
		where = "from this form (MYQIMA &gt; Cancel MYQIMA Inspection)"

	frappe.throw(
		f"Quality Inspection <b>{doc.name}</b> has an active MyQima booking (Order <b>{order}</b>). "
		f"Please cancel the MyQima booking {where} before cancelling this inspection.",
		title="MyQima Booking Active",
	)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_service_date(qc_date):
	"""
	QIMA rejects inspection dates <= current time.
	Use qc_date if it's a future date, otherwise default to tomorrow.
	"""
	today = date.today()

	if qc_date:
		if isinstance(qc_date, str):
			qc_date = datetime.strptime(qc_date[:10], "%Y-%m-%d").date()
		elif hasattr(qc_date, "date"):
			qc_date = qc_date.date()

		if qc_date > today:
			return qc_date

	return today + timedelta(days=1)


def _fmt_date(d):
	"""Convert date → DD-MMM-YYYY e.g. 27-APR-2026"""
	if isinstance(d, str):
		d = datetime.strptime(d[:10], "%Y-%m-%d").date()
	return d.strftime("%d-%b-%Y").upper()


@frappe.whitelist()
def cancel_inspection_booking(
	quality_inspection_name, reason="Customer requested cancellation", reason_options=""
):
	"""
	Called from the 'Cancel QIMA Inspection' button on Quality Inspection form, for inspections
	not created from a Quality Request. The booking details stay on the inspection with
	MyQima Booking Cancelled checked.

	Args:
		quality_inspection_name (str): name of the Quality Inspection doc
		reason (str): cancellation reason (required by QIMA)
		reason_options (str): cancellation reason detail (optional)

	Returns:
		dict: { "success": True }
	"""
	doc = frappe.get_doc("Quality Inspection", quality_inspection_name)

	# The order is shared by every inspection of the Quality Request, so only the request can cancel it
	if doc.get("custom_quality_request"):
		frappe.throw(
			f"This inspection was booked through Quality Request <b>{doc.custom_quality_request}</b>. "
			f"Please cancel the MyQima booking from there."
		)

	if not _get_myqima_value(doc, "myqima_inspection_created"):
		frappe.throw("No QIMA inspection booking found for this document.")

	if not _get_myqima_value(doc, "myqima_booking_id"):
		frappe.throw("Booking ID is missing. Cannot cancel.")

	if _get_myqima_value(doc, "myqima_booking_cancelled"):
		frappe.throw("The MyQima booking of this document is already cancelled.")

	item_group = frappe.db.get_value("Item", doc.item_code, "item_group")
	cred_row = get_category_credentials(item_group)

	settings = frappe.get_single("MyQima Settings")
	headers = get_headers(settings, get_valid_token(cred_row))

	with myqima_lock(doc.name):
		_delete_inspection(settings, cred_row, headers, doc, reason, reason_options)
		_set_myqima_values(doc, {"myqima_booking_cancelled": 1})
		frappe.db.commit()

	return {"success": True}


def _delete_inspection(settings, cred_row, headers, doc, reason, reason_options="", reference=None):
	"""DELETE /v1.0/inspection/{userId}/{orderId}?reason=...

	The call is logged against `reference` when given (e.g. the Quality Request), else against doc.
	"""
	params = {"reason": reason}
	if reason_options:
		params["reason_options"] = reason_options

	booking_id = _get_myqima_value(doc, "myqima_booking_id")
	url = f"{settings.base_url}/user/{cred_row.userid}/inspection/{booking_id}"

	try:
		response = call_myqima_api(
			"Cancel Inspection",
			"DELETE",
			url,
			reference=reference or doc,
			booking_id=booking_id,
			headers=headers,
			params=params,
			timeout=30,
		)
	except requests.exceptions.RequestException as exc:
		frappe.throw(f"[QIMA] Network error while cancelling booking:<br>{exc}")

	if not response.ok:
		frappe.throw(
			f"[QIMA] Cancellation failed.<br>"
			f"Status: {response.status_code}<br>"
			f"Response: {response.text}"
		)

	frappe.logger().info(f"[QIMA] Booking cancelled — Order ID: {booking_id}")


@frappe.whitelist()
def fetch_inspection_report(quality_inspection_name):
	"""
	Called from the 'Fetch QIMA Report' and 'Re-fetch QIMA Report' buttons on Quality Inspection form.

	Fetches only this inspection's report, by its own product ID. An order booked through a
	Quality Request is shared by all its inspections; the others are fetched from their own form
	or all at once from the Quality Request. A report already fetched is fetched again only
	while its report decision is pending, or while it could not be applied.
	1. Checks inspection status via GET /user/{userId}/inspection-order/{orderId}
	2. If FINISHED, fetches report via GET /user/{userId}/interactive-report/{productId}?orderId={orderId}
	3. Saves status, result, decision, and report URL back to the QI doc.
	4. Throws, after saving, when the report could not be applied to the inspection.
	"""
	doc = frappe.get_doc("Quality Inspection", quality_inspection_name)

	if not _get_myqima_value(doc, "myqima_inspection_created"):
		frappe.throw("No QIMA inspection booking found for this document.")

	if not _get_myqima_value(doc, "myqima_booking_id"):
		frappe.throw("Booking ID is missing.")

	if _get_myqima_value(doc, "myqima_booking_cancelled"):
		frappe.throw("The MyQima booking of this document is cancelled, so there is no report to fetch.")

	if not is_report_due(doc):
		frappe.throw(
			f"Report already fetched for this document. "
			f"Result: <b>{_get_myqima_value(doc, 'myqima_overall_result')}</b> | "
			f"Decision: <b>{_get_myqima_value(doc, 'myqima_report_decision')}</b>"
		)

	item_group = frappe.db.get_value("Item", doc.item_code, "item_group")
	cred_row = get_category_credentials(item_group)

	settings = frappe.get_single("MyQima Settings")
	headers = get_headers(settings, get_valid_token(cred_row))

	# Same lock as the Quality Request's own fetch and the report scheduler
	with myqima_lock(doc.get("custom_quality_request") or doc.name):
		inspection_status, failed = fetch_order_reports(settings, cred_row, headers, [doc])

	throw_report_update_errors(failed)

	if inspection_status != "FINISHED":
		frappe.msgprint(
			f"Inspection is not yet finished. Current status: <b>{inspection_status}</b>",
			title="Not Ready",
			indicator="orange",
		)

	doc.reload()

	return {
		"inspection_status": inspection_status,
		"overall_result": _get_myqima_value(doc, "myqima_overall_result", None),
		"report_decision": _get_myqima_value(doc, "myqima_report_decision", None),
		"decision_reason": _get_myqima_value(doc, "myqima_decision_reason", None),
		"report_url": _get_myqima_value(doc, "myqima_report_url", None),
		"decision_pending": bool(_get_myqima_value(doc, "myqima_decision_pending")),
	}


def fetch_order_reports(settings, cred_row, headers, inspections, reference=None):
	"""
	Fetch the MyQima report of every inspection booked under one order.

	The order's status is checked once and saved on every inspection. Only once the order is
	FINISHED is each inspection's report fetched, by its own product ID, as MyQima reports one
	product at a time. Inspections of a consolidated booking share one product, whose report is
	fetched once for them all. Inspections whose report is already fetched are skipped, unless its
	report decision is still pending or it could not be applied. Each report is committed as soon
	as it is saved, so a failure part way keeps the reports fetched before it. A report that
	cannot be applied to its inspection does not stop the others; it is returned in failed, for
	the caller to throw once all are done (see throw_report_update_errors).

	Args:
		settings (Document): MyQima Settings
		cred_row (Document): QIMA Category Credentials row the order was booked with
		headers (dict): authenticated request headers
		inspections (list[Document]): Quality Inspections sharing one MyQima order
		reference (Document): document the status check is logged against; defaults to the first inspection

	Returns:
		tuple[str, list[str]]: the order's status text e.g. 'FINISHED', and one
			"<inspection>: <reason>" line per inspection whose report could not be applied
	"""
	inspection_status = _get_inspection_status(settings, cred_row, headers, inspections[0], reference)

	for doc in inspections:
		_set_myqima_values(doc, {"myqima_inspection_status": inspection_status})
	frappe.db.commit()

	if inspection_status != "FINISHED":
		return inspection_status, []

	reports = {}
	failed = []
	for doc in inspections:
		if not is_report_due(doc):
			continue

		product_id = _get_myqima_value(doc, "myqima_product_id")
		if product_id not in reports:
			reports[product_id] = _get_interactive_report(settings, cred_row, headers, doc)

		try:
			_apply_product_report(settings, headers, doc, reports[product_id])
		except MyQimaReportUpdateError as exc:
			failed.append(f"<b>{doc.name}</b>: {exc}")

	return inspection_status, failed


def _apply_product_report(settings, headers, doc, report_data):
	"""Attach the PDF of the inspection's product report and update the inspection from it.

	A report whose decision is pending (see is_decision_pending) is only saved on the MyQima
	Details row, flagged to be fetched again: nothing is mapped on the inspection itself, not
	even the PDF, until a later fetch brings the decision. A consolidated booking's inspection is
	mapped from the decision of its own SKU (see get_report_values).

	MyQima Report Not Applied stays checked until the report is applied, so a report that cannot
	be applied, or a worker stopped part way, is fetched again. Its PDF is attached only once.

	Raises:
		MyQimaReportUpdateError: when the report cannot be applied to the inspection, e.g. a
			consolidated report with no decision for its SKU, after the report itself is saved
	"""
	values = get_report_values(doc, report_data)
	report_url = report_data.get("downloadUrlOfReport", "")
	decision_pending = values.found and is_decision_pending(settings, values.report_decision, values.source)

	# Downloaded once the decision is made, so fetching again while pending adds no copies, nor
	# does fetching again a report that was attached but could not be applied
	already_attached = _get_myqima_value(doc, "myqima_report_not_applied") and doc.get("attach_qi_doc")
	file_url = (
		None
		if decision_pending or already_attached
		else _download_and_attach_report(settings, headers, doc, report_url)
	)

	_set_myqima_values(
		doc,
		{
			"myqima_overall_result": values.overall_result,
			"myqima_report_decision": values.report_decision,
			"myqima_decision_reason": values.decision_reason,
			"myqima_report_url": report_url,
			"myqima_report_fetched": 1,
			"myqima_decision_pending": int(decision_pending),
			"myqima_report_not_applied": int(not decision_pending),
		},
	)

	# The report is attached whatever its result; status and quantities follow MyQima Settings
	if file_url:
		frappe.db.set_value("Quality Inspection", doc.name, "attach_qi_doc", file_url, update_modified=False)

	frappe.db.commit()

	if not decision_pending:
		if not values.found:
			raise MyQimaReportUpdateError(
				f"The consolidated MyQima report has no decision for its SKU {doc.item_code} "
				f"(no productReference with referencePoNumber {doc.name})."
			)

		verdict = get_inspection_verdict(
			settings, values.overall_result, values.report_decision, values.source
		)

		# Before the outcome, which may submit the inspection with its Accepted Qty
		apply_produced_qty(doc, settings, verdict, values.produced_qty, values.source)
		apply_report_outcome(doc, settings, verdict)

		_set_myqima_values(doc, {"myqima_report_not_applied": 0})
		frappe.db.commit()

	frappe.logger().info(
		f"[QIMA] Report fetched — {doc.name} | Order: {_get_myqima_value(doc, 'myqima_order_number')} | "
		f"Result: {values.overall_result} | Decision: {values.report_decision}"
		f"{' (pending, to be fetched again)' if decision_pending else ''}"
	)


def _get_inspection_status(settings, cred_row, headers, doc, reference=None):
	"""GET /user/{userId}/inspection-order/{orderId} → returns statusText string

	The call is logged against `reference` when given (e.g. the Quality Request), else against doc.
	"""
	booking_id = _get_myqima_value(doc, "myqima_booking_id")
	url = f"{settings.base_url}/user/{cred_row.userid}/inspection-order/{booking_id}"

	try:
		response = call_myqima_api(
			"Inspection Status",
			"GET",
			url,
			reference=reference or doc,
			booking_id=booking_id,
			headers=headers,
			timeout=30,
		)
	except requests.exceptions.RequestException as exc:
		frappe.throw(f"[QIMA] Network error checking inspection status:<br>{exc}")

	if not response.ok:
		frappe.throw(
			f"[QIMA] Status check failed.<br>"
			f"Status: {response.status_code}<br>"
			f"Response: {response.text}"
		)

	data = response.json()
	return data.get("content", {}).get("orderGeneralInfo", {}).get("statusText", "")


def _get_interactive_report(settings, cred_row, headers, doc):
	"""GET /user/{userId}/interactive-report/{productId}?orderId={orderId} → returns content dict"""
	product_id = _get_myqima_value(doc, "myqima_product_id")
	booking_id = _get_myqima_value(doc, "myqima_booking_id")
	url = (
		f"{settings.base_url}/user/{cred_row.userid}"
		f"/interactive-report/{product_id}"
		f"?orderId={booking_id}"
	)

	try:
		response = call_myqima_api(
			"Interactive Report",
			"GET",
			url,
			reference=doc,
			booking_id=booking_id,
			headers=headers,
			timeout=30,
		)
	except requests.exceptions.RequestException as exc:
		frappe.throw(f"[QIMA] Network error fetching report:<br>{exc}")

	if not response.ok:
		frappe.throw(
			f"[QIMA] Report fetch failed.<br>"
			f"Status: {response.status_code}<br>"
			f"Response: {response.text}"
		)

	return response.json().get("content", {})


def _download_and_attach_report(settings, headers, doc, report_url):
	"""Download PDF from QIMA and attach it to the Quality Inspection doc."""

	if not report_url:
		frappe.log_error("No report URL provided", f"[QIMA] Attach Report {doc.name}")
		return None

	try:
		response = call_myqima_api(
			"Download Report",
			"GET",
			report_url,
			reference=doc,
			booking_id=_get_myqima_value(doc, "myqima_booking_id"),
			log_response=False,
			headers=headers,
			timeout=60,
		)
	except requests.exceptions.RequestException as exc:
		frappe.throw(f"[QIMA] Failed to download report PDF:<br>{exc}")

	if not response.ok:
		frappe.throw(
			f"[QIMA] Report download failed.<br>"
			f"Status: {response.status_code}<br>"
			f"Response: {response.text}"
		)

	# One order can cover several products, so the item code tells their reports apart
	order_number = _get_myqima_value(doc, "myqima_order_number")
	file_name = f"QIMA_Report_{order_number or doc.name}_{doc.item_code}.pdf"

	# Save to Frappe file system and attach to the doc
	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": file_name,
			"attached_to_doctype": "Quality Inspection",
			"attached_to_name": doc.name,
			"attached_to_field": "attach_qi_doc",
			"content": response.content,
			"is_private": 1,
		}
	)
	file_doc.save(ignore_permissions=True)

	frappe.logger().info(f"[QIMA] Report PDF attached — {file_name} → {doc.name}")

	return file_doc.file_url


@frappe.whitelist()
def can_show_qima_actions(quality_inspection):
	qi = frappe.get_doc("Quality Inspection", quality_inspection)

	if not qi.custom_import_supplier:
		return False

	item_group = frappe.db.get_value("Item", qi.item_code, "item_group")

	settings = frappe.get_cached_doc("MyQima Settings")

	allowed_groups = {row.item_group for row in settings.myqima_allowed_item_group}

	return item_group in allowed_groups
