import json
from datetime import date, datetime, timedelta

import frappe
import requests

from qimaone_integrations.myqima.utils import get_valid_token


@frappe.whitelist()
def create_inspection_booking(qr_item_name):
	"""
	Called from the 'Create Inspection' button osn the Quality Request Item child row.

	Args:
		qr_item_name (str): name of the Quality Request Item row (e.g. 'falhud4g5r')

	Returns:
		dict: { "booking_id": "<qima_order_id>" }
	"""
	row = frappe.get_doc("Quality Request Item", qr_item_name)

	if row.custom_myqima_inspection_created:
		frappe.throw(
			f"Inspection already created for this row. Booking ID: <b>{row.custom_myqima_booking_id}</b>"
		)

	supplier_synced = frappe.db.get_value("Supplier", row.supplier, "custom_myqima_sync_status")
	if not supplier_synced:
		frappe.throw(
			f"Supplier <b>{row.supplier}</b> is not mapped with MyQima. "
			f"Please sync the supplier before creating an inspection booking."
		)
	settings = frappe.get_single("MyQima Settings")
	token = get_valid_token()

	# get_valid_token may return the full generate-token response dict on first run
	if isinstance(token, dict):
		token = token.get("content", {}).get("token", {}).get("token", "")

	headers = {
		"Content-Type": "application/json",
		"Ai-Api-Access-Token": settings.api_key,
		"Referer": settings.referer,
		"Authorization": f"Bearer {token}",
		"Connection": "keep-alive",
	}

	payload = _build_payload(row, settings)

	frappe.log_error(
		json.dumps(payload, indent=2, default=str),
		f"[QIMA] Payload for QR Item {qr_item_name}",
	)

	booking_id, order_number, product_id = _post_inspection(settings, headers, payload, row)

	# Persist on child row
	# custom_myqima_booking_id  → UUID (orderId)   used for API lookups
	# custom_myqima_order_number → human ref       e.g. Q2600212068-PP, shown to users
	frappe.db.set_value(
		"Quality Request Item",
		qr_item_name,
		{
			"custom_myqima_booking_id": booking_id,
			"custom_myqima_order_number": order_number,
			"custom_myqima_product_id": product_id,
			"custom_myqima_inspection_created": 1,
		},
		update_modified=False,
	)

	frappe.db.commit()

	return {"booking_id": booking_id, "order_number": order_number, "product_id": product_id}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_payload(row, settings):
	category_id, family_id, type_id = _get_qima_item_ids(row.item_code)

	service_date = _fmt_date(_get_service_date(row.qc_date))

	return {
		"userId": settings.userid or "",
		"serviceDate": service_date,
		"shipDate": service_date,
		"serviceType": "1",
		"bookingType": "General",
		"referenceNumber": row.purchase_order or "",
		"supplierCode": row.supplier or "",
		"products": [
			{
				"name": row.item_name,
				"categoryId": category_id,
				"familyId": family_id,
				"typeId": type_id,
				"refs": [
					{
						"poNumber": row.purchase_order or "",
						"skuCode": row.item_code or "",
						"qty": int(row.qc_qty or 0),
					}
				],
				"checkList": None,
			}
		],
		"customField1": "",
		"customField2": "",
		"customField3": "",
		"performInQimaone": None,
		"allowChangeInspectionDate": True,
	}


def _get_qima_item_ids(item_code):
	"""Fetch category/family/type from custom_myqima_item_master child table on Item."""
	try:
		rows = frappe.get_all(
			"Myqima Item Master",
			filters={"parent": item_code, "parentfield": "custom_myqima_item_master", "parenttype": "Item"},
			fields=["category_id", "family_id", "product_type_id"],
			limit=1,
		)
		if rows:
			r = rows[0]
			return (
				r.get("category_id") or "",
				r.get("family_id") or "",
				r.get("product_type_id") or "",
			)
	except Exception as e:
		frappe.log_error(
			f"Could not fetch QIMA item IDs for {item_code}: {e}",
			"[QIMA] Item master lookup error",
		)

	return "", "", ""


def _post_inspection(settings, headers, payload, row):
	"""POST to QIMA and return the booking ID string."""
	url = f"{settings.base_url}/v1.0/inspection"

	try:
		response = requests.post(url, headers=headers, json=payload, timeout=30)
	except requests.exceptions.RequestException as exc:
		frappe.throw(f"[QIMA] Network error for item <b>{row.item_code}</b>:<br>{exc}")

	frappe.log_error(
		json.dumps(
			{"status_code": response.status_code, "body": _safe_json(response)},
			indent=2,
		),
		f"[QIMA] API Response for QR Item {row.name}",
	)

	if not response.ok:
		frappe.throw(
			f"[QIMA] Booking failed for item <b>{row.item_code}</b>.<br>"
			f"Status: {response.status_code}<br>"
			f"Response: {response.text}"
		)

	data = response.json()

	# Confirmed response structure:
	# data["content"]["orderGeneralInfo"]["orderId"]  → the booking ID
	# data["content"]["orderGeneralInfo"]["orderNumber"] → human-readable ref e.g. "Q2600212068-PP"
	order_general_info = data.get("content", {}).get("orderGeneralInfo", {})
	booking_id = order_general_info.get("orderId", "")
	order_number = order_general_info.get("orderNumber", "")
	products = data.get("content", {}).get("products", [])
	product_id = products[0].get("productBean", {}).get("productId", "") if products else ""

	if not booking_id:
		frappe.throw(
			f"[QIMA] Booking succeeded (HTTP {response.status_code}) but no order ID returned.<br>"
			f"Full response: {response.text}"
		)

	frappe.logger().info(f"[QIMA] Booking created — Order ID: {booking_id} | Order Number: {order_number}")

	return booking_id, order_number, product_id


def _fmt_date(d):
	"""Convert date/datetime/string → DD-MMM-YYYY (QIMA format). e.g. 2026-04-27 → 27-APR-2026"""
	from datetime import datetime

	if not d:
		return ""
	if isinstance(d, str):
		d = datetime.strptime(d[:10], "%Y-%m-%d")
	return d.strftime("%d-%b-%Y").upper()


def _safe_json(response):
	try:
		return response.json()
	except Exception:
		return response.text


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

	# fallback: tomorrow
	return today + timedelta(days=1)


def _fmt_date(d):
	"""Convert date → DD-MMM-YYYY e.g. 27-APR-2026"""
	if isinstance(d, str):
		d = datetime.strptime(d[:10], "%Y-%m-%d").date()
	return d.strftime("%d-%b-%Y").upper()
