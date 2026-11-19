import frappe

# Custom fields of the old MyQima code, merged by accident and never used on this site. The current
# code keeps a booking in MyQima Details and reads no category IDs or supplier codes from Item or Supplier.
UNUSED_CUSTOM_FIELDS = {
	"Quality Inspection": (
		"custom_myqima_booking_id",
		"custom_myqima_order_number",
		"custom_myqima_inspection_created",
		"custom_myqima_product_id",
	),
	"Supplier": ("custom_myqima_sync_status", "custom_myqima_supplier_code"),
	"Item": ("custom_myqima_item_master",),
}

ITEM_MASTER = "Myqima Item Master"

# Login and token fields once at the top of MyQima Settings; logins now live in its Category Credentials rows
UNUSED_SETTINGS_FIELDS = ("account", "password", "userid", "access_token", "refresh_key", "token_expiry")


def execute():
	"""Remove the old MyQima custom fields, Myqima Item Master and the removed Settings fields' values."""
	for doctype, fieldnames in UNUSED_CUSTOM_FIELDS.items():
		for fieldname in fieldnames:
			name = frappe.db.get_value("Custom Field", {"dt": doctype, "fieldname": fieldname})
			if name:
				frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)

	if frappe.db.exists("DocType", ITEM_MASTER):
		frappe.delete_doc("DocType", ITEM_MASTER, ignore_permissions=True, force=True)

	frappe.db.delete("Singles", {"doctype": "MyQima Settings", "field": ("in", UNUSED_SETTINGS_FIELDS)})
	frappe.db.delete("__Auth", {"doctype": "MyQima Settings", "fieldname": "password"})
	frappe.clear_document_cache("MyQima Settings", "MyQima Settings")
