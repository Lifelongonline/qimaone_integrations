import frappe
import requests

from qimaone_integrations.myqima.customizations.quality_inspection.quality_inspection import (
	_delete_inspection,
	_fmt_date,
	_get_service_date,
	_set_myqima_values,
	fetch_order_reports,
	throw_report_update_errors,
)
from qimaone_integrations.myqima.doctype.myqima_error_log.myqima_error_log import (
	BOOKING_JOB,
	REPORT_JOB,
	resolve_myqima_error,
)
from qimaone_integrations.myqima.utils import (
	call_myqima_api,
	can_bypass_booking_check,
	get_category_credentials,
	get_headers,
	get_valid_token,
	myqima_lock,
)

# One booking has a single supplier, MyQima user and inspection date, so every row
# sent in it must agree on these. Rows that differ would need separate bookings,
# which is not supported yet.
SHARED_BOOKING_FIELDS = {
	"supplier_code": "SAP Supplier Sub Code",
	"userid": "MyQima User",
	"qc_date": "QC Date",
}

# Checkbox on the Quality Request that books its rows as one consolidated MyQima product
CONSOLIDATED_FIELD = "custom_push_consolidated_items_in_myqima"

# Most items QIMA takes as references of one consolidated product on our account
MAX_CONSOLIDATED_REFS = 10


@frappe.whitelist()
def get_myqima_bookings(quality_request_name):
	"""Return every inspected row of a Quality Request with its MyQima state, for the form buttons."""
	doc = frappe.get_doc("Quality Request", quality_request_name)
	doc.check_permission("read")

	return get_booking_rows(doc)


@frappe.whitelist()
def create_inspection_booking(quality_request_name):
	"""
	Called from the 'Create Inspection Booking' button on the Quality Request form.

	Books one MyQima inspection for the rows not booked yet, one product per row. Every such
	row must be eligible for MyQima and agree on supplier, MyQima user and QC date; otherwise
	nothing is booked. Each inspection then stores the shared order and its own product ID,
	which its report is fetched by.

	Args:
		quality_request_name (str): name of the submitted Quality Request e.g. 'QR26-27-00016'

	Returns:
		dict: { "booking_id": "...", "order_number": "...", "inspections": ["MAT-QA-...", ...] }
	"""
	doc = frappe.get_doc("Quality Request", quality_request_name)
	doc.check_permission("write")

	with myqima_lock(doc.name):
		return book_quality_request(doc)


def book_quality_request(doc):
	"""
	Book the not yet booked rows of a Quality Request in one MyQima order; see create_inspection_booking.

	Shared by the form button and the auto booking scheduler, which both call it holding the
	Quality Request's myqima_lock. Resolves the request's open booking error log on success.
	"""
	if doc.docstatus != 1:
		frappe.throw("Please submit the Quality Request before creating an inspection booking.")

	rows = [row for row in get_booking_rows(doc) if not row.booked]
	if not any(row.eligible for row in rows):
		frappe.throw("There are no rows left to book with MyQima on this Quality Request.")

	validate_rows_eligible(rows)

	for row in rows:
		row.cred_row = get_category_credentials(row.item_group)
		row.userid = row.cred_row.userid

	validate_single_booking(rows)

	consolidated = bool(doc.get(CONSOLIDATED_FIELD))
	if consolidated:
		validate_consolidated_size(rows)

	cred_row = rows[0].cred_row
	settings = frappe.get_single("MyQima Settings")
	headers = get_headers(settings, get_valid_token(cred_row))

	payload = _build_payload(doc, rows, cred_row.userid, consolidated)
	order, products = _post_inspection(settings, headers, payload, doc)
	product_ids = _match_product_ids(doc, rows, products, consolidated)

	for row in rows:
		# A row booked again after a cancelled booking starts clean, so no report is carried over
		_set_myqima_values(
			frappe.get_doc("Quality Inspection", row.quality_inspection),
			{
				"myqima_booking_id": order.get("orderId"),
				"myqima_order_number": order.get("orderNumber"),
				"myqima_product_id": product_ids.get(row.quality_inspection, ""),
				"myqima_inspection_created": 1,
				"myqima_booking_cancelled": 0,
				"myqima_inspection_status": "",
				"myqima_overall_result": "",
				"myqima_report_decision": "",
				"myqima_decision_reason": "",
				"myqima_report_url": "",
				"myqima_consolidated": int(consolidated),
				"myqima_report_fetched": 0,
				"myqima_decision_pending": 0,
				"myqima_report_not_applied": 0,
			},
		)
		_set_request_row_values(
			row, {"custom_myqima_inspection_created": 1, "custom_myqima_booking_cancelled": 0}
		)

	resolve_myqima_error(doc.name, BOOKING_JOB)
	frappe.db.commit()

	return {
		"booking_id": order.get("orderId"),
		"order_number": order.get("orderNumber"),
		"inspections": [row.quality_inspection for row in rows],
	}


@frappe.whitelist()
def cancel_inspection_booking(
	quality_request_name, reason="Customer requested cancellation", reason_options=""
):
	"""
	Called from the 'Cancel MYQIMA Inspection' button on the Quality Request form.

	Cancels every active MyQima order found on the request's inspections. The booking details
	stay on each inspection, and the inspection and request row get MyQima Booking Cancelled
	checked, which lets the documents be cancelled and the rows be booked again. Normally that is one order, but
	inspections booked one by one before booking moved to the Quality Request carry their own.
	Each order is committed once QIMA confirms it, so a failure part way leaves the earlier
	cancellations recorded.

	Args:
		quality_request_name (str): name of the Quality Request
		reason (str): cancellation reason (required by QIMA)
		reason_options (str): cancellation reason detail (optional)

	Returns:
		dict: { "cancelled": ["<booking_id>", ...] }
	"""
	doc = frappe.get_doc("Quality Request", quality_request_name)
	doc.check_permission("write")

	with myqima_lock(doc.name):
		return _cancel_bookings(doc, reason, reason_options)


def _cancel_bookings(doc, reason, reason_options):
	"""Cancel every active order of the Quality Request on QIMA and flag it cancelled here."""
	bookings = group_by_booking(row for row in get_booking_rows(doc) if row.booked)
	if not bookings:
		frappe.throw("No MyQima inspection booking found for this Quality Request.")

	settings = frappe.get_single("MyQima Settings")

	for rows in bookings.values():
		cred_row = get_category_credentials(rows[0].item_group)
		headers = get_headers(settings, get_valid_token(cred_row))
		inspections = [frappe.get_doc("Quality Inspection", row.quality_inspection) for row in rows]

		_delete_inspection(settings, cred_row, headers, inspections[0], reason, reason_options, reference=doc)

		for inspection in inspections:
			_set_myqima_values(inspection, {"myqima_booking_cancelled": 1})

		for row in rows:
			_set_request_row_values(row, {"custom_myqima_booking_cancelled": 1})

		frappe.db.commit()

	return {"cancelled": list(bookings)}


@frappe.whitelist()
def fetch_inspection_report(quality_request_name):
	"""
	Called from the 'Fetch MYQIMA Report' button on the Quality Request form.

	Fetches the MyQima report of every booked row whose report is not fetched yet, was fetched
	with its report decision pending, or could not be applied, one order at a time: the order's
	status is checked once,
	and once it is FINISHED each inspection gets the report of its own product. Normally the
	request has one order, but inspections booked one by one before booking moved to the Quality
	Request carry their own. An order not finished yet only has its status saved.

	Args:
		quality_request_name (str): name of the Quality Request

	Returns:
		list[dict]: every booked row with its MyQima status, result and decision after the fetch
	"""
	doc = frappe.get_doc("Quality Request", quality_request_name)
	doc.check_permission("write")

	with myqima_lock(doc.name):
		if not fetch_quality_request_reports(doc):
			frappe.throw("There are no MyQima reports left to fetch on this Quality Request.")

	return [row for row in get_booking_rows(doc) if row.booked]


def fetch_quality_request_reports(doc):
	"""
	Fetch the reports of the Quality Request's active orders still due; see fetch_inspection_report.

	Shared by the form button and the auto report scheduler, which both call it holding the
	Quality Request's myqima_lock. Resolves the request's open report error log once every order
	was checked without an error.

	Raises:
		MyQimaReportUpdateError: once every order is checked, listing the inspections whose report
			could not be applied; their reports are saved and fetched again on the next fetch

	Returns:
		int: the number of orders checked; 0 when there was nothing left to fetch
	"""
	bookings = group_by_booking(row for row in get_booking_rows(doc) if row.booked and row.report_due)
	if not bookings:
		return 0

	settings = frappe.get_single("MyQima Settings")
	failed = []

	for rows in bookings.values():
		cred_row = get_category_credentials(rows[0].item_group)
		headers = get_headers(settings, get_valid_token(cred_row))
		inspections = [frappe.get_doc("Quality Inspection", row.quality_inspection) for row in rows]

		_status, order_failed = fetch_order_reports(settings, cred_row, headers, inspections, reference=doc)
		failed.extend(order_failed)

	throw_report_update_errors(failed)

	resolve_myqima_error(doc.name, REPORT_JOB)
	frappe.db.commit()

	return len(bookings)


def validate(doc, method=None):
	"""Refuse a Quality Request with more MyQima rows than MyQima Settings allows, when that check is on."""
	settings = frappe.get_cached_doc("MyQima Settings")
	if not settings.validate_sku_qty_for_qr_creation:
		return

	limit = settings.no_of_sku_per_quality_request
	myqima_rows = _get_myqima_rows(doc, settings)
	if len(myqima_rows) <= limit:
		return

	frappe.throw(
		f"A Quality Request can have at most <b>{limit}</b> MyQima SKUs, but this one has "
		f"<b>{len(myqima_rows)}</b>. Please move the extra rows to another Quality Request.",
		title="Too Many SKUs for MyQima",
	)


def _get_myqima_rows(doc, settings):
	"""Return the Quality Request's rows for an import supplier whose item group is enabled for MyQima."""
	rows = [row for row in doc.quality_request_item if row.custom_import_supplier]
	if not rows:
		return []

	item_groups = _get_item_groups(rows)
	allowed_groups = {row.item_group for row in settings.myqima_allowed_item_group}

	return [row for row in rows if item_groups.get(row.item_code) in allowed_groups]


def _get_item_groups(rows):
	"""Return {item code: item group} for the items of the given rows."""
	return dict(
		frappe.get_all(
			"Item",
			filters={"name": ["in", list({row.item_code for row in rows})]},
			fields=["name", "item_group"],
			as_list=True,
		)
	)


def before_cancel(doc, method=None):
	"""Refuse to cancel a Quality Request while any of its rows has an active MyQima booking.

	Cancelling the booking from the form keeps its details with MyQima Booking Cancelled
	checked, after which the request can be cancelled. Users with BOOKING_CANCEL_BYPASS_ROLE
	skip this check.
	"""
	if can_bypass_booking_check():
		return

	booked = [row for row in get_booking_rows(doc) if row.booked]
	if not booked:
		return

	rows = "<br>".join(
		f"Row {row.idx} ({row.item_code}, {row.quality_inspection}): "
		f"Order <b>{row.order_number or row.booking_id}</b>"
		for row in booked
	)
	frappe.throw(
		f"These rows have an active MyQima booking:<br><br>{rows}<br><br>"
		f"Please cancel the MyQima booking first (MYQIMA &gt; Cancel MYQIMA Inspection), "
		f"then cancel this Quality Request.",
		title="MyQima Booking Active",
	)


def group_by_booking(rows):
	"""Return {booking ID: [rows]} for the given booking rows, keeping their order."""
	bookings = {}
	for row in rows:
		bookings.setdefault(row.booking_id, []).append(row)
	return bookings


def get_booking_rows(doc):
	"""
	Return each Quality Request row that has an inspection, with what MyQima needs to book it.

	A row is eligible when its inspection is for an import supplier and its item group is in
	MyQima Allowed Item Group, the same rule the Quality Inspection form used; otherwise
	not_eligible_reason says why. A row is booked when its inspection carries a MyQima booking
	ID that is not cancelled, and carries the inspection's report status, result and decision
	once fetched. Its report is due until fetched with a decision and applied to the inspection.
	A row whose booking is cancelled can be booked again.
	"""
	rows = [row for row in doc.quality_request_item if row.quality_inspection]
	if not rows:
		return []

	inspection_names = [row.quality_inspection for row in rows]

	import_inspections = set(
		frappe.get_all(
			"Quality Inspection",
			filters={"name": ["in", inspection_names], "custom_import_supplier": 1},
			pluck="name",
		)
	)
	item_groups = _get_item_groups(rows)
	allowed_groups = {
		row.item_group for row in frappe.get_cached_doc("MyQima Settings").myqima_allowed_item_group
	}
	bookings = {
		detail.parent: detail
		for detail in frappe.get_all(
			"MyQima Details",
			filters={
				"parenttype": "Quality Inspection",
				"parentfield": "custom_myqima_details",
				"parent": ["in", inspection_names],
			},
			fields=[
				"parent",
				"myqima_booking_id",
				"myqima_order_number",
				"myqima_product_id",
				"myqima_inspection_status",
				"myqima_overall_result",
				"myqima_report_decision",
				"myqima_decision_reason",
				"myqima_report_fetched",
				"myqima_decision_pending",
				"myqima_report_not_applied",
				"myqima_booking_cancelled",
			],
		)
	}

	booking_rows = []
	for row in rows:
		item_group = item_groups.get(row.item_code)
		booking = bookings.get(row.quality_inspection) or {}
		report_fetched = bool(booking.get("myqima_report_fetched"))
		decision_pending = bool(booking.get("myqima_decision_pending"))
		report_not_applied = bool(booking.get("myqima_report_not_applied"))

		not_eligible_reason = None
		if row.quality_inspection not in import_inspections:
			not_eligible_reason = "Supplier is not an import supplier"
		elif item_group not in allowed_groups:
			not_eligible_reason = f"Item Group {item_group} is not enabled for MyQima"

		booking_rows.append(
			frappe._dict(
				name=row.name,
				idx=row.idx,
				item_code=row.item_code,
				item_name=row.item_name,
				item_group=item_group,
				qc_qty=row.qc_qty,
				qc_date=row.qc_date,
				supplier_code=row.custom_sap_supplier_sub_code,
				quality_inspection=row.quality_inspection,
				eligible=not not_eligible_reason,
				not_eligible_reason=not_eligible_reason,
				booked=bool(booking.get("myqima_booking_id")) and not booking.get("myqima_booking_cancelled"),
				booking_id=booking.get("myqima_booking_id"),
				order_number=booking.get("myqima_order_number"),
				product_id=booking.get("myqima_product_id"),
				inspection_status=booking.get("myqima_inspection_status"),
				overall_result=booking.get("myqima_overall_result"),
				report_decision=booking.get("myqima_report_decision"),
				decision_reason=booking.get("myqima_decision_reason"),
				report_fetched=report_fetched,
				decision_pending=decision_pending,
				report_not_applied=report_not_applied,
				report_due=not report_fetched or decision_pending or report_not_applied,
			)
		)

	return booking_rows


def validate_rows_eligible(rows):
	"""Throw, listing why, if any row to be booked is not eligible for MyQima."""
	not_eligible = [row for row in rows if not row.eligible]
	if not not_eligible:
		return

	reasons = "<br>".join(
		f"Row {row.idx} ({row.item_code}, {row.quality_inspection}): <b>{row.not_eligible_reason}</b>"
		for row in not_eligible
	)
	frappe.throw(
		f"No booking was created. Every row must be eligible for MyQima:<br><br>{reasons}",
		title="Rows Cannot Be Booked",
	)


def validate_single_booking(rows):
	"""Throw unless every row has a supplier sub code and all rows agree on SHARED_BOOKING_FIELDS."""
	missing = [str(row.idx) for row in rows if not row.supplier_code]
	if missing:
		frappe.throw(
			f"SAP Supplier Sub Code is missing on row(s) <b>{', '.join(missing)}</b>. "
			f"It is required as the supplier code of the MyQima booking."
		)

	for field, label in SHARED_BOOKING_FIELDS.items():
		if len({row[field] for row in rows}) == 1:
			continue

		values = "<br>".join(f"Row {row.idx} ({row.item_code}): <b>{row[field] or '—'}</b>" for row in rows)
		frappe.throw(
			f"All rows booked together must have the same {label}.<br><br>{values}",
			title="Rows Cannot Be Booked Together",
		)


def validate_consolidated_size(rows):
	"""Throw if there are more rows than QIMA takes as references of one consolidated product."""
	if len(rows) <= MAX_CONSOLIDATED_REFS:
		return

	frappe.throw(
		f"A consolidated MyQima booking takes at most {MAX_CONSOLIDATED_REFS} items, "
		f"but {len(rows)} rows are left to book. Uncheck <b>Push Consolidated Items in MyQima Portal</b> "
		f"to book each item as its own product, or move the extra rows to another Quality Request.",
		title="Too Many Items to Consolidate",
	)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _set_request_row_values(row, values):
	"""Set the booking checkboxes on the Quality Request row; the request is submitted, so write directly."""
	frappe.db.set_value("Quality Request Item", row.name, values, update_modified=False)


def _build_payload(doc, rows, userid, consolidated=False):
	"""
	Build the booking body with the Quality Request as the reference.

	Each row is one product, or with consolidated one reference of a single product, which
	MyQima inspects into one report.
	"""
	service_date = _fmt_date(_get_service_date(rows[0].qc_date))
	products = _consolidated_products(doc, rows) if consolidated else _row_products(rows)

	return {
		"userId": userid or "",
		"serviceDate": service_date,
		"shipDate": service_date,
		"serviceType": "1",
		"bookingType": "General",
		"referenceNumber": doc.name,
		"supplierCode": rows[0].supplier_code,
		"clientRefNb": doc.name,
		"products": products,
		"customField1": _fmt_date(doc.posting_date),
		"customField2": "",
		"customField3": "",
		"performInQimaone": None,
		"allowChangeInspectionDate": True,
	}


def _row_products(rows):
	"""Return one product per row, each with the row as its only reference."""
	return [{"name": row.item_name, "refs": [_product_ref(row)], "checkList": None} for row in rows]


def _consolidated_products(doc, rows):
	"""Return a single product named after the Quality Request, with every row as one of its references."""
	return [
		{
			"name": f"Consolidated Items - {doc.name}",
			"refs": [_product_ref(row) for row in rows],
			"checkList": None,
		}
	]


def _product_ref(row):
	"""Return the product reference of a row."""
	return {
		# poNumber carries the inspection name, so each product maps back to its QI
		"poNumber": row.quality_inspection,
		"skuCode": row.item_code or "",
		"qty": int(row.qc_qty or 0),
	}


def _post_inspection(settings, headers, payload, doc):
	"""POST to QIMA and return (orderGeneralInfo, products) from the response."""
	url = f"{settings.base_url}/v1.0/inspection"

	try:
		response = call_myqima_api(
			"Inspection Booking",
			"POST",
			url,
			reference=doc,
			headers=headers,
			json=payload,
			timeout=30,
		)
	except requests.exceptions.RequestException as exc:
		frappe.throw(f"[QIMA] Network error for Quality Request <b>{doc.name}</b>:<br>{exc}")

	if not response.ok:
		frappe.throw(
			f"[QIMA] Booking failed for Quality Request <b>{doc.name}</b>.<br>"
			f"Status: {response.status_code}<br>"
			f"Response: {response.text}"
		)

	content = response.json().get("content") or {}
	order = content.get("orderGeneralInfo") or {}

	if not order.get("orderId"):
		frappe.throw(
			f"[QIMA] Booking succeeded (HTTP {response.status_code}) but no order ID returned.<br>"
			f"Full response: {response.text}"
		)

	frappe.logger().info(
		f"[QIMA] Booking created — Order ID: {order.get('orderId')} | Order Number: {order.get('orderNumber')}"
	)

	return order, content.get("products") or []


def _match_product_ids(doc, rows, products, consolidated=False):
	"""
	Return {inspection name: product ID}, matching products on poNumber rather than position.

	A consolidated booking has a single product whose ID every inspection shares. An inspection
	with no matching product is logged and left without a product ID instead of throwing: the
	order already exists on QIMA, and throwing would lose it.
	"""
	if consolidated:
		bean = (products[0].get("productBean") or {}) if len(products) == 1 else {}
		product_ids = {row.quality_inspection: bean.get("productId") for row in rows}
	else:
		product_ids = {}
		for product in products:
			bean = product.get("productBean") or {}
			product_ids[bean.get("poNumber")] = bean.get("productId")

	unmatched = [row.quality_inspection for row in rows if not product_ids.get(row.quality_inspection)]
	if unmatched:
		frappe.log_error(
			f"No product in the booking response for inspection(s) {', '.join(unmatched)}. "
			f"They were saved without a product ID.",
			f"[QIMA] Unmatched products for Quality Request {doc.name}",
		)

	return product_ids
