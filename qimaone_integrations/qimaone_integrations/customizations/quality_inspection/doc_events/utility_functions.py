import json

import frappe
import requests
from frappe import _

from qimaone_integrations.qimaone_integrations.doctype.qima_settings.api.api import create_qima_logs


def cancel_po_on_qima_portal(doc):
	"""This method is used to cancel the PO on Qima portal when the Quality Inspection is cancelled/Deleted in ERPNext."""
	qima_settings = frappe.get_single("Qima Settings")

	url = qima_settings.po_fetch_url
	payload = f"referenceFilter={doc.name}"
	token = qima_settings.refresh_token
	cancel_url = qima_settings.po_cancel_url
	headers = {"Content-Type": "application/x-www-form-urlencoded", "Authorization": f"Bearer {token}"}
	response = requests.request("GET", url, headers=headers, data=payload)
	create_qima_logs("PO Fetch for Update", response)
	if response.status_code == 200:
		data = response.json()
		cancel_po(data, cancel_url, token)
	else:
		frappe.msgprint(_(f"Failed to fetch PO from Qima portal. Response: {response.text}"))


def cancel_po(data, cancel_url, token):
	if data and data.get("content"):
		po_number = data.get("content")[0].get("id")
		cancel_url = cancel_url.format(purchaseOrderId=po_number)
		payload = json.dumps("CANCELLED")
		headers = {
			"Content-Type": "application/json",
			"Accept": "application/json",
			"Authorization": f"Bearer {token}",
		}
		response = requests.request("PATCH", cancel_url, headers=headers, data=payload)
		create_qima_logs("PO Status Update", response)
		if response.status_code == 200:
			frappe.msgprint(_(f"PO {po_number} cancelled successfully on Qima portal."))
		else:
			frappe.msgprint(_(f"Failed to cancel PO {po_number} on Qima portal. Response: {response.text}"))
	else:
		frappe.msgprint(_({"No matching PO found on Qima portal to cancel."}))


def validate_supplier(doc):
	qima_settings = frappe.get_single("Qima Settings")
	if not qima_settings.enable_supplier_validation or not doc.custom_domestic_supplier:
		return
	mapped_item_groups = [row.item_group for row in qima_settings.qimaone_allowed_item_groups]
	item_group = frappe.db.get_value("Item", doc.item_code, "item_group")
	if item_group not in mapped_item_groups:
		return
	mapped_suppliers = [row.erp_supplier for row in qima_settings.qimaone_overlap]
	if doc.supplier not in mapped_suppliers:
		frappe.throw(_("Supplier is not mapped in Qima Integration."))
