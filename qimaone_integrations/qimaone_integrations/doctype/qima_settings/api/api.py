import csv
import io
import json

import frappe
import requests
from frappe import _
from frappe.utils import now


@frappe.whitelist()
def generate_refresh_token(doc):
	"""Generate refresh token for QimaOne API."""
	doc = json.loads(doc)
	try:
		response = requests.post(
			doc.get("refresh_token_url"),
			json={
				"email": doc.get("email_id"),
				"password": doc.get("password"),
				"apiToken": doc.get("api_token"),
			},
		)
		create_qima_logs("Generate Refresh Token", response)
		if response.status_code == 200:
			data = response.json()
			return data.get("id_token")

		frappe.throw(
			f"Failed to generate refresh token for QimaOne API: {response.status_code} - {response.text}"
		)

	except Exception as e:
		frappe.throw(f"Failed to generate refresh token for QimaOne API: {e}")


@frappe.whitelist()
def append_draft_inspections_to_csv():
	"""Prepare CSV from draft inspections and send it to the QIMA import API."""

	qima_settings = frappe.get_single("Qima Settings")

	token = qima_settings.refresh_token
	po_import_url = qima_settings.po_import_url
	unit = qima_settings.default_qima_uom
	file_path = qima_settings.po_import_file_path

	# Normalize CSV header values for case-insensitive matching.
	def normalize(value):
		return (value or "").strip().replace("\ufeff", "").upper()

	qima_settings = frappe.get_single("Qima Settings")
	mappings = [row for row in qima_settings.qimaone_supplier_map if row.qimaone and row.erp]

	# adding unit column because there is no mapping of this field but it is required in csv for import api, so we are adding it manually in both qima_columns and erp_fields list.
	qima_columns = [row.qimaone for row in mappings] + ["UNIT"]
	erp_fields = [row.erp for row in mappings]

	inspections = frappe.get_all(
		"Quality Inspection",
		filters={"docstatus": 0, "custom_domestic_supplier": 1},
		fields=erp_fields,
	)
	if not inspections:
		frappe.throw(_("No inspection found."))
	for row in inspections:
		row["UNIT"] = unit

	erp_fields.extend(["UNIT"])

	file_doc = frappe.get_doc("File", {"file_url": file_path})
	abs_path = file_doc.get_full_path()

	try:
		with open(abs_path, newline="", encoding="utf-8-sig") as f:
			all_rows = list(csv.reader(f))

		if not all_rows:
			frappe.throw("CSV template is empty")

		header_row = all_rows[0]
		col_count = len(header_row)

		# Keep only non-empty existing rows after header
		data_rows = [row for row in all_rows[1:] if any((cell or "").strip() for cell in row)]

		label_to_index = {normalize(label): idx for idx, label in enumerate(header_row)}

		for inspection in inspections:
			row = [""] * col_count
			has_value = False

			for qima_col, erp_field in zip(qima_columns, erp_fields, strict=False):
				col_idx = label_to_index.get(normalize(qima_col))

				if col_idx is not None:
					value = inspection.get(erp_field)
					if value is not None:
						row[col_idx] = str(value)
						has_value = True

			if has_value:
				data_rows.append(row)

		output = io.StringIO()
		writer = csv.writer(output)
		writer.writerow(header_row)
		writer.writerows(data_rows)
		create_po_on_qima(token, po_import_url, output.getvalue().encode("utf-8"))

	except Exception as e:
		frappe.throw(_(f"Error processing CSV file: {e}"))


def create_po_on_qima(token, url, file):
	"""Call the QIMAOne import API with the generated CSV file."""
	payload = {}
	files = {"file": ("import_purchase_order_updated.csv", file, "text/csv")}
	headers = {"Authorization": f"Bearer {token}"}
	response = requests.request("POST", url, headers=headers, data=payload, files=files)
	create_qima_logs("PO Imports", response)


def create_qima_logs(title, message):
	"""Create logs for QIMAOne API interactions."""
	log = frappe.new_doc("QIMA Logs")
	log.status = message.status_code
	log.response_message = message.text
	log.status_code = message.status_code
	log.title = title
	log.created_on = now()
	if message.status_code == 200 or message.status_code == 202:
		log.status = "Success"
	else:
		log.status = "Failed"

	location = message.headers.get("location")
	if location:
		log.process_id = location.rstrip("/").split("/")[-1]
	log.insert(ignore_permissions=True)


@frappe.whitelist()
def fetch_process_status(process_id):
	"""Fetch the status of a process from QIMAOne using the process ID. This is typically used to check the status of an import process after initiating it."""
	qima_settings = frappe.get_single("Qima Settings")
	token = qima_settings.refresh_token
	url = qima_settings.process_status_url + process_id

	headers = {"Authorization": f"Bearer {token}"}
	response = requests.request("GET", url, headers=headers)
	return response.json()
