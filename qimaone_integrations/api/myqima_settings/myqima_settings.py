import frappe

from qimaone_integrations.myqima.utils import __generate_token_manual, __refresh_token_manual


@frappe.whitelist()
def generate_token_manual():
	return __generate_token_manual()


@frappe.whitelist()
def refresh_token_manual():
	return __refresh_token_manual()
