import json
from datetime import date, datetime, timedelta

import frappe
import requests

from qimaone_integrations.myqima.utils import get_valid_token


@frappe.whitelist()
def create_inspection_booking(quality_inspection_name):
	"""
	Called from the 'Create QIMA Inspection' button on Quality Inspection form.

	Args:
		quality_inspection_name (str): name of the Quality Inspection doc e.g. 'MAT-QA-2026-00236'

	Returns:
		dict: { "booking_id": "...", "order_number": "...", "product_id": "..." }
	"""
	doc = frappe.get_doc("Quality Inspection", quality_inspection_name)

	if doc.custom_myqima_inspection_created:
		frappe.throw(
			f"Inspection already created for this document. Booking ID: <b>{doc.custom_myqima_booking_id}</b>"
		)

	supplier_synced = frappe.db.get_value("Supplier", doc.supplier, "custom_myqima_sync_status")
	if not supplier_synced:
		frappe.throw(
			f"Supplier <b>{doc.supplier}</b> is not mapped with MyQima. "
			f"Please sync the supplier before creating an inspection booking."
		)

	settings = frappe.get_single("MyQima Settings")
	token = get_valid_token()

	if isinstance(token, dict):
		token = token.get("content", {}).get("token", {}).get("token", "")

	headers = {
		"Content-Type": "application/json",
		"Ai-Api-Access-Token": settings.api_key,
		"Referer": settings.referer,
		"Authorization": f"Bearer {token}",
		"Connection": "keep-alive",
	}

	payload = _build_payload(doc, settings)

	frappe.log_error(
		json.dumps(payload, indent=2, default=str),
		f"[QIMA] Payload for Quality Inspection {quality_inspection_name}",
	)

	booking_id, order_number, product_id = _post_inspection(settings, headers, payload, doc)

	frappe.db.set_value(
		"Quality Inspection",
		quality_inspection_name,
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


def _build_payload(doc, settings):
	category_id, family_id, type_id = _get_qima_item_ids(doc.item_code)

	service_date = _fmt_date(_get_service_date(doc.report_date))

	return {
		"userId": settings.userid or "",
		"serviceDate": service_date,
		"shipDate": service_date,
		"serviceType": "1",
		"bookingType": "General",
		"referenceNumber": doc.reference_name or "",
		"supplierCode": doc.supplier or "",
		"products": [
			{
				"name": doc.item_name,
				"categoryId": category_id,
				"familyId": family_id,
				"typeId": type_id,
				"refs": [
					{
						"poNumber": doc.reference_name or "",
						"skuCode": doc.item_code or "",
						"qty": int(doc.custom_offered_qty or 0),
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


def _post_inspection(settings, headers, payload, doc):
	"""POST to QIMA and return (booking_id, order_number, product_id)."""
	url = f"{settings.base_url}/v1.0/inspection"

	try:
		response = requests.post(url, headers=headers, json=payload, timeout=30)
	except requests.exceptions.RequestException as exc:
		frappe.throw(f"[QIMA] Network error for item <b>{doc.item_code}</b>:<br>{exc}")

	frappe.log_error(
		json.dumps(
			{"status_code": response.status_code, "body": _safe_json(response)},
			indent=2,
		),
		f"[QIMA] API Response for Quality Inspection {doc.name}",
	)

	if not response.ok:
		frappe.throw(
			f"[QIMA] Booking failed for item <b>{doc.item_code}</b>.<br>"
			f"Status: {response.status_code}<br>"
			f"Response: {response.text}"
		)

	data = response.json()

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


def _safe_json(response):
	try:
		return response.json()
	except Exception:
		return response.text


@frappe.whitelist()
def cancel_inspection_booking(
	quality_inspection_name, reason="Customer requested cancellation", reason_options=""
):
	"""
	Called from the 'Cancel QIMA Inspection' button on Quality Inspection form.

	Args:
		quality_inspection_name (str): name of the Quality Inspection doc
		reason (str): cancellation reason (required by QIMA)
		reason_options (str): cancellation reason detail (optional)

	Returns:
		dict: { "success": True }
	"""
	doc = frappe.get_doc("Quality Inspection", quality_inspection_name)

	if not doc.custom_myqima_inspection_created:
		frappe.throw("No QIMA inspection booking found for this document.")

	if not doc.custom_myqima_booking_id:
		frappe.throw("Booking ID is missing. Cannot cancel.")

	settings = frappe.get_single("MyQima Settings")
	token = get_valid_token()

	if isinstance(token, dict):
		token = token.get("content", {}).get("token", {}).get("token", "")

	headers = {
		"Content-Type": "application/json",
		"Ai-Api-Access-Token": settings.api_key,
		"Referer": settings.referer,
		"Authorization": f"Bearer {token}",
		"Connection": "keep-alive",
	}

	_delete_inspection(settings, headers, doc, reason, reason_options)

	frappe.db.set_value(
		"Quality Inspection",
		quality_inspection_name,
		{
			"custom_myqima_inspection_created": 0,
			"custom_myqima_booking_id": "",
			"custom_myqima_order_number": "",
			"custom_myqima_product_id": "",
		},
		update_modified=False,
	)

	frappe.db.commit()

	return {"success": True}


def _delete_inspection(settings, headers, doc, reason, reason_options=""):
	"""DELETE /v1.0/inspection/{userId}/{orderId}?reason=..."""
	params = {"reason": reason}
	if reason_options:
		params["reason_options"] = reason_options

	url = f"{settings.base_url}/user/{settings.userid}/inspection/{doc.custom_myqima_booking_id}"

	frappe.log_error(
		f"DELETE {url} | params: {params}",
		f"[QIMA] Cancel request for Quality Inspection {doc.name}",
	)

	try:
		response = requests.delete(url, headers=headers, params=params, json={}, timeout=30)
	except requests.exceptions.RequestException as exc:
		frappe.throw(f"[QIMA] Network error while cancelling booking:<br>{exc}")

	frappe.log_error(
		json.dumps(
			{"status_code": response.status_code, "body": _safe_json(response)},
			indent=2,
		),
		f"[QIMA] Cancel Response for Quality Inspection {doc.name}",
	)

	if not response.ok:
		frappe.throw(
			f"[QIMA] Cancellation failed.<br>"
			f"Status: {response.status_code}<br>"
			f"Response: {response.text}"
		)

	frappe.logger().info(f"[QIMA] Booking cancelled — Order ID: {doc.custom_myqima_booking_id}")
