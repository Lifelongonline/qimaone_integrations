import frappe

from qimaone_integrations.migrate import create_custom_fields
from qimaone_integrations.qimaone_integrations.customizations.address.doc_events.utility_functions import (
	set_sap_supplier_sub_code,
)

FIELD = "custom_sap_supplier_sub_code"


def execute():
	"""Give existing import-supplier addresses their SAP Supplier Sub Code, as saving them would.

	A sub code is only issued when an address is saved, and only for a supplier ticked as Import
	Supplier, so addresses made before the field existed have none. Quality Requests and Quality
	Inspections pick it up on their next save.
	"""
	# Patches run before after_migrate, which is where the app creates its custom fields
	create_custom_fields()

	for column in ("custom_sap_customer_code", "import_supplier"):
		if not frappe.db.has_column("Supplier", column):
			print(f"SAP sub code backfill skipped: Supplier has no {column} field")
			return

	# Only addresses linked to an import supplier with an SAP code, oldest first, so the numbers
	# follow the order the addresses were made in
	addresses = frappe.db.sql_list(
		f"""
		select dl.parent
		from `tabDynamic Link` dl
		join `tabSupplier` supplier on supplier.name = dl.link_name
		where dl.parenttype = 'Address'
			and dl.link_doctype = 'Supplier'
			and ifnull(dl.{FIELD}, '') = ''
			and supplier.import_supplier = 1
			and ifnull(supplier.custom_sap_customer_code, '') != ''
		order by dl.creation
		"""
	)

	for name in dict.fromkeys(addresses):
		doc = frappe.get_doc("Address", name)
		set_sap_supplier_sub_code(doc)
		for link in doc.links:
			if link.get(FIELD) and not frappe.db.get_value("Dynamic Link", link.name, FIELD):
				frappe.db.set_value("Dynamic Link", link.name, FIELD, link.get(FIELD), update_modified=False)
