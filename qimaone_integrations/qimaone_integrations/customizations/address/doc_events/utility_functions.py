import frappe
from frappe.query_builder.functions import Max
from frappe.utils import cint

SUB_CODE_SEPARATOR = "SG"


def set_sap_supplier_sub_code(doc):
	"""Stamp every import-supplier link row of the address with <sap supplier code>SG###.

	Only suppliers ticked as Import Supplier get a sub code. The number restarts at 001
	for each supplier and is never re-issued, so an address that already carries a sub
	code keeps it. A site without the Supplier's Import Supplier field issues none.
	"""
	if not frappe.db.has_column("Supplier", "import_supplier"):
		return

	last_used = {}
	for link in doc.get("links") or []:
		if link.link_doctype != "Supplier" or link.get("custom_sap_supplier_sub_code"):
			continue

		supplier = frappe.db.get_value(
			"Supplier", link.link_name, ["custom_sap_customer_code", "import_supplier"], as_dict=True
		)
		if not supplier or not supplier.import_supplier or not supplier.custom_sap_customer_code:
			continue

		sap_code = supplier.custom_sap_customer_code

		if sap_code not in last_used:
			last_used[sap_code] = get_last_used_sub_code_no(sap_code)
		last_used[sap_code] += 1

		link.custom_sap_supplier_sub_code = f"{sap_code}{SUB_CODE_SEPARATOR}{last_used[sap_code]:03d}"


def get_last_used_sub_code_no(sap_code):
	"""Highest SG number already issued against this supplier's SAP code.

	Every sub code shares the same prefix and is zero padded to three digits, so
	the lexical MAX is also the numeric one.
	"""
	prefix = f"{sap_code}{SUB_CODE_SEPARATOR}"
	dynamic_link = frappe.qb.DocType("Dynamic Link")
	data = (
		frappe.qb.from_(dynamic_link)
		.select(Max(dynamic_link.custom_sap_supplier_sub_code).as_("sub_code"))
		.where(dynamic_link.custom_sap_supplier_sub_code.like(f"{prefix}%"))
	).run(as_dict=1)

	if data and data[0]["sub_code"]:
		return cint(data[0]["sub_code"][len(prefix) :])
	return 0
