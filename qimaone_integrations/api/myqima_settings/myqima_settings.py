import frappe

from qimaone_integrations.myqima.utils import __generate_token_manual, __refresh_token_manual, token_lock


@frappe.whitelist(methods=["POST"])
def generate_token_manual():
	"""Log every MyQima Category Credentials row in again and save its new token."""
	return _update_tokens(__generate_token_manual)


@frappe.whitelist(methods=["POST"])
def refresh_token_manual():
	"""Refresh the token of every MyQima Category Credentials row."""
	return _update_tokens(__refresh_token_manual, hint="<br>Try Generate Token instead.")


def _update_tokens(update_token, hint=""):
	"""Run update_token on each Category Credentials row with a login; return how many were updated."""
	frappe.only_for("System Manager")

	settings = frappe.get_single("MyQima Settings")
	rows = [row for row in settings.myqima_category_credentials if row.account]
	if not rows:
		frappe.throw("Please add a login in MYQIMA Category Credentials first.")

	for row in rows:
		with token_lock(row):
			try:
				update_token(settings, row)
			except frappe.ValidationError:
				raise
			except Exception as exc:
				frappe.throw(f"Row {row.idx} (<b>{row.account}</b>): {exc}{hint}")

	return len(rows)
