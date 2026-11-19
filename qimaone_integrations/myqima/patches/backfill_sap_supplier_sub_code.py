import frappe

from qimaone_integrations.migrate import create_custom_fields
from qimaone_integrations.qimaone_integrations.customizations.address.doc_events.utility_functions import (
	set_sap_supplier_sub_code,
)

FIELD = "custom_sap_supplier_sub_code"


def execute():
	"""Give existing supplier addresses their SAP Supplier Sub Code, as saving them would.

	A sub code is only issued when an address is saved, so addresses made before the field
	existed have none. Quality Requests and Quality Inspections pick it up on their next save.
	"""
	# Patches run before after_migrate, which is where the app creates its custom fields
	create_custom_fields()

	if not frappe.db.has_column("Supplier", "custom_sap_customer_code"):
		print("SAP sub code backfill skipped: Supplier has no SAP code field (lifelong_customizations)")
		return

	# Oldest address first, so the numbers follow the order the addresses were made in
	addresses = frappe.get_all(
		"Dynamic Link",
		filters={"parenttype": "Address", "link_doctype": "Supplier", FIELD: ("is", "not set")},
		pluck="parent",
		order_by="creation asc",
	)

	for name in dict.fromkeys(addresses):
		doc = frappe.get_doc("Address", name)
		set_sap_supplier_sub_code(doc)
		for link in doc.links:
			if link.get(FIELD) and not frappe.db.get_value("Dynamic Link", link.name, FIELD):
				frappe.db.set_value("Dynamic Link", link.name, FIELD, link.get(FIELD), update_modified=False)
