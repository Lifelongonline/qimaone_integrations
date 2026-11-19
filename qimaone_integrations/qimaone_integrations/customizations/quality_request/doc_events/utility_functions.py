import frappe


def set_sap_supplier_sub_code(doc):
	"""Sync every request row with the sub code of the supplier address it points at.

	Recomputed on each save so changing or clearing the address keeps the row honest.
	An address created before this field existed carries no sub code, and the row is
	simply left blank.
	"""
	for row in doc.quality_request_item:
		row.custom_sap_supplier_sub_code = get_address_sub_code(row.custom_supplier_address, row.supplier)


def get_address_sub_code(address, supplier):
	"""Sub code of the supplier link row on the given address."""
	if not address or not supplier:
		return None

	return frappe.db.get_value(
		"Dynamic Link",
		{
			"parenttype": "Address",
			"parent": address,
			"link_doctype": "Supplier",
			"link_name": supplier,
		},
		"custom_sap_supplier_sub_code",
	)


@frappe.whitelist()
def get_supplier_address_sub_code(address, supplier):
	"""Called from the Quality Request form to fill the sub code as soon as an address is picked."""
	frappe.has_permission("Address", doc=address, throw=True)

	return get_address_sub_code(address, supplier)
