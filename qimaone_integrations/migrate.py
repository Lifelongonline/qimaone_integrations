import json
import os

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def after_migrate():
	create_custom_fields()
	create_roles()
	# create_property_setter()


def create_roles():
	"""Create the roles this app checks for, if they do not exist yet."""
	from qimaone_integrations.myqima.utils import BOOKING_CANCEL_BYPASS_ROLE

	if frappe.db.exists("Role", BOOKING_CANCEL_BYPASS_ROLE):
		return

	frappe.get_doc({"doctype": "Role", "role_name": BOOKING_CANCEL_BYPASS_ROLE, "desk_access": 1}).insert(
		ignore_permissions=True
	)

def create_custom_fields():
	CUSTOM_FIELDS = {}
	print("Creating/Updating Custom Fields....")
	path = os.path.join(os.path.dirname(__file__), "qimaone_integrations/custom_fields")
	for file in os.listdir(path):
		with open(os.path.join(path, file), "r") as f:
			CUSTOM_FIELDS.update(json.load(f))
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)


def create_property_setter():
	print("Creating/Updating Property Setters....")
	path = os.path.join(os.path.dirname(__file__), "qimaone_integrations/property_setters")
	for file in os.listdir(path):
		with open(os.path.join(path, file), "r") as f:
			property_setters = json.load(f)
			for doctype, properties in property_setters.items():
				for args in properties:
					if not args.get("doctype"):
						args["doctype"] = doctype
					make_property_setter(**args)
