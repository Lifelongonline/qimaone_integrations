import csv
import io
import json

import frappe
import requests
from frappe import _
from frappe.query_builder import DocType
from frappe.query_builder.functions import Coalesce
from frappe.utils import cint, flt, get_datetime, getdate, now, now_datetime, nowdate


@frappe.whitelist()
def generate_refresh_token():
	"""Generate refresh token for QimaOne API."""
	doc = frappe.get_single("Qima Settings")
	if not doc.email_id or not doc.get_password or not doc.api_token:
		frappe.throw(
			_(
				"Email ID, Password and API Token are required to generate refresh token for QimaOne API"
			)
		)
	try:
		response = requests.post(
			doc.refresh_token_url,
			json={
				"email": doc.email_id,
				"password": doc.password,
				"apiToken": doc.api_token,
			},
		)
		create_qima_logs("Generate Refresh Token", response)
		if response.status_code == 200:
			data = response.json()
			doc.refresh_token = data.get("id_token")
			doc.save(ignore_permissions=True)
			return "Success"

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
	supplier_mapping = [
		row.erp_supplier for row in qima_settings.qimaone_overlap if row.erp_supplier and row.qimaone_supplier
	]

	QualityInspection = DocType("Quality Inspection")
	Item = DocType("Item")

	allowed_groups = [row.item_group for row in qima_settings.qimaone_allowed_item_groups]
	query = (
		frappe.qb.from_(QualityInspection)
		.join(Item)
		.on(QualityInspection.item_code == Item.name)
		.select(*(QualityInspection[field] for field in erp_fields))
		.where(QualityInspection.docstatus == 0)
		.where(QualityInspection.custom_domestic_supplier == 1)
		.where(QualityInspection.supplier.isin(supplier_mapping))
		.where(QualityInspection.creation.between(get_datetime(qima_settings.from_date), now_datetime()))
		.where(Item.item_group.isin(allowed_groups))
	)

	query_for_unmapped_suppliers = (
		frappe.qb.from_(QualityInspection)
		.join(Item)
		.on(QualityInspection.item_code == Item.name)
		.select(QualityInspection.supplier, QualityInspection.name)
		.where(QualityInspection.docstatus == 0)
		.where(QualityInspection.custom_domestic_supplier == 1)
		.where(QualityInspection.supplier.notin(supplier_mapping))
		.where(QualityInspection.creation.between(get_datetime(qima_settings.from_date), now_datetime()))
		.where(Item.item_group.isin(allowed_groups))
	)

	unmapped_suppliers = query_for_unmapped_suppliers.run(as_dict=True)
	if unmapped_suppliers:
		message = frappe._dict(
			{
				"status_code": 404,
				"text": f" inspection not synced due to supplier not mapped: {unmapped_suppliers}",
				"headers": {},
			}
		)
		create_qima_logs("PO Imports", message)

	inspections = query.run(as_dict=True)

	if not inspections:
		frappe.throw(_("No inspection found."))

	for row in inspections:
		row["custom_actual_qc_date"] = getdate(row.get("custom_actual_qc_date"))
		row["UNIT"] = unit

	erp_fields.extend(["UNIT"])

	file_doc = frappe.get_doc("File", {"file_url": file_path})
	abs_path = file_doc.get_full_path()

	try:
		with open(abs_path, newline="", encoding="utf-8-sig") as f:
			all_rows = list(csv.reader(f))

		if not all_rows:
			frappe.throw("CSV template is empty")

		header_row = qima_columns
		col_count = len(header_row)

		# Keep only non-empty existing rows after header
		data_rows = [row for row in all_rows[1:] if any((cell or "").strip() for cell in row)]

		label_to_index = {normalize(label): idx for idx, label in enumerate(header_row)}

		overlap_map_supplier = {
			row.erp_supplier: row.qimaone_supplier
			for row in qima_settings.qimaone_overlap
			if row.erp_supplier and row.qimaone_supplier
		}
		overlap_map_address = {
			row.erp_supplier_address: row.qimaone_address
			for row in qima_settings.qimaone_overlap
			if row.erp_supplier_address and row.qimaone_address
		}

		for inspection in inspections:
			row = [""] * col_count
			has_value = False

			for qima_col, erp_field in zip(qima_columns, erp_fields, strict=False):
				col_idx = label_to_index.get(normalize(qima_col))

				if col_idx is not None:
					value = inspection.get(erp_field)
					if value in overlap_map_supplier:
						value = overlap_map_supplier[value]
					if value in overlap_map_address:
						value = overlap_map_address[value]
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
	log.response_message = message.text if title != "Download Inspection Report" else ""
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


@frappe.whitelist()
def product_uploads():
	"""Prepare CSV from draft inspections and send it to the QIMA import API."""

	qima_settings = frappe.get_single("Qima Settings")

	token = qima_settings.refresh_token
	po_import_url = qima_settings.product_import_url
	file_path = qima_settings.product_import_file_path

	def normalize(value):
		return (value or "").strip().replace("\ufeff", "").upper()

	qima_settings = frappe.get_single("Qima Settings")
	mappings = [row for row in qima_settings.qimaone_item_map if row.qimaone_item_code and row.erp_item_code]

	qima_columns = [row.qimaone_item_code for row in mappings]
	erp_fields = [row.erp_item_code for row in mappings]

	products = frappe.get_all(
		"Item",
		filters={"disabled": 0, "custom_uploaded_on_qima": 1},
		fields=erp_fields,
	)
	if not products:
		frappe.throw(_("No products found."))

	for row in products:
		barcode = frappe.get_all(
			"Item Barcode",
			filters={"barcode_type": "EAN", "parent": row.item_name},
			fields=["barcode"],
		)
		if barcode:
			row["GTIN"] = barcode[0].get("barcode")

	file_doc = frappe.get_doc("File", {"file_url": file_path})
	abs_path = file_doc.get_full_path()

	try:
		with open(abs_path, newline="", encoding="utf-8-sig") as f:
			all_rows = list(csv.reader(f))

		if not all_rows:
			frappe.throw("CSV template is empty")

		header_row = [*qima_columns, "GTIN"]
		col_count = len(header_row)

		data_rows = [row for row in all_rows[1:] if any((cell or "").strip() for cell in row)]

		label_to_index = {normalize(label): idx for idx, label in enumerate(header_row)}

		for inspection in products:
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
		create_product_on_qima(token, po_import_url, output.getvalue().encode("utf-8"))

	except Exception as e:
		frappe.throw(_(f"Error processing CSV file: {e}"))


def create_product_on_qima(token, url, file):
	"""Call the QIMAOne import API with the generated CSV file."""
	payload = {}
	files = {"file": ("import_products.csv", file, "text/csv")}
	headers = {"Authorization": f"Bearer {token}"}
	response = requests.request("POST", url, headers=headers, data=payload, files=files)
	create_qima_logs("Product Imports", response)


@frappe.whitelist()
def fetch_inspections():
	"""Fetch inspection reports from QIMAOne and create corresponding documents in ERPNext."""
	qima_settings = frappe.get_single("Qima Settings")
	token = qima_settings.refresh_token
	url = qima_settings.fetch_inspection_url
	from_date = qima_settings.from_date_for_inspection_sync
	count = frappe.db.get_value(
		"Quality Inspection",
		{
			"docstatus": 0,
			"custom_domestic_supplier": 1,
			"creation": [
				"between",
				[get_datetime(qima_settings.from_date), now_datetime()],
			],
		},
		"count(*)",
	)
	headers = {"Authorization": f"Bearer {token}"}
	payload = {"size": str(cint(count) + 10)}
	response = requests.request("GET", url, headers=headers, params=payload)

	if response.status_code == 200:
		create_qima_logs("Quality Inspection Report", response)
		data = response.json()
		download_and_attach_inspection_report(token, from_date, data)
	else:
		frappe.throw(
			f"Failed to fetch inspection reports from QIMAOne API: {response.status_code} - {response.text}"
		)


def download_and_attach_inspection_report(token, from_date, data):
	"""Download a specific inspection report from QIMAOne and attach it to the corresponding Quality Inspection document in ERPNext."""
	from frappe.utils import getdate

	filtered_data = {}
	for item in data.get("content", []):
		inspection_date = item.get("inspectionDate")
		if (
			inspection_date
			and inspection_date >= getdate(from_date).strftime("%Y-%m-%d")
			and item.get("reportDecision") in ["ACCEPTED", "APPROVED"]
		):
			filtered_data[item.get("id")] = item

	headers = {"Authorization": f"Bearer {token}"}
	for row in filtered_data.values():
		frappe.enqueue(
			download_and_attach_report_to_qc,
			row=row,
			headers=headers,
			queue="long",
			timeout=1800,
			job_name="Download Inspection Report",
			enqueue_after_commit=True,
		)
	frappe.msgprint(f"{len(filtered_data)} Inspection report download has been queued.")


def download_and_attach_report_to_qc(row, headers):
	"""Attach the downloaded inspection report to the corresponding Quality Inspection document in ERPNext."""

	def attach_report_to_qc(
		qc_id, inspection_id, file_content, product_qty, inspection_result, report_decision
	):
		import base64

		file_name = f"QIMA_Inspection_Report_{inspection_id}.pdf"
		encoded_file = base64.b64encode(file_content).decode("utf-8")

		# update quality inspection
		qc_doc = frappe.get_doc("Quality Inspection", qc_id)
		# qc_doc.remaining_qty = product_qty
		# qc_doc.rejected_qty = qc_doc.custom_offered_qty - product_qty
		qc_doc.custom_inspection_report_status = report_decision
		mode_of_assembly = frappe.db.get_value("Owner", {"parent": qc_doc.item_code}, "mode_of_assembly")
		qc_doc.custom_mode_of_assembly = mode_of_assembly
		# if inspection_result == "COMPLETED":
		# 	qc_doc.status = "Accepted"

		qc_doc.save(ignore_permissions=True)
		qc_doc.submit()

		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": file_name,
				"attached_to_doctype": "Quality Inspection",
				"attached_to_name": qc_id,
				"content": encoded_file,
				"decode": True,
				"attached_to_field": "attach_qi_doc",
			}
		)
		file_doc.insert(ignore_permissions=True)

		qc_doc.attach_qi_doc = file_doc.file_url
		qc_doc.save(ignore_permissions=True)
		qc_doc.submit()
	# for row in filtered_data:
	inspection_id = row.get("id")
	inspection_result = row.get("inspectionResult")
	report_decision = row.get("reportDecision")
	product_qty = flt(row.get("productQuantity"))
	po_ref = row.get("purchaseOrderReference")
	download_url = row.get("links")[0].get("href")

	qc_id = frappe.db.get_value(
		"Quality Inspection",
		{"name": po_ref, "docstatus": 0, "custom_domestic_supplier": 1},
		"name",
	)

	if qc_id:
		response = requests.request("GET", download_url, headers=headers)
		if response.status_code == 200:
			file_content = response.content
			# attach the downloaded inspection report to relevant quality inspection and also update the QC
			attach_report_to_qc(
				qc_id, inspection_id, file_content, product_qty, inspection_result, report_decision
			)
			create_qima_logs("Download Inspection Report", response)
		else:
			frappe.throw(
				f"Failed to download inspection report from QIMAOne API: {response.status_code} - {response.text}"
			)
