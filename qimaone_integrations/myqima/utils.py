import json
from datetime import datetime, timedelta

import frappe
import requests


def __generate_token_manual():
	settings = frappe.get_single("MyQima Settings")

	url = f"{settings.base_url}/auth/v2/token"

	headers = {
		"Content-Type": "application/json",
		"ai-api-access-token": settings.api_key,
		"Referer": settings.referer,
	}

	payload = {
		"account": settings.account,
		"password": settings.get_password("password"),
		"userType": "client",
		"tokenExpire": "3600",
	}

	response = requests.post(url, headers=headers, json=payload)

	frappe.log_error(
		json.dumps({"status_code": response.status_code, "response_text": response.text}, indent=2),
		"QIMA TOKEN RESPONSE",
	)

	if not response.ok:
		frappe.throw(f"QIMA Token API failed: {response.text}")

	data = response.json()

	token_data = data.get("content", {}).get("token", {})

	settings.access_token = token_data.get("token")
	settings.refresh_key = token_data.get("refreshKey")

	expiry = datetime.fromtimestamp(int(token_data.get("validBefore")))
	settings.token_expiry = expiry

	settings.save(ignore_permissions=True)

	return data


def __refresh_token_manual():
	settings = frappe.get_single("MyQima Settings")

	if not settings.access_token or not settings.refresh_key:
		frappe.throw("Token or Refresh Key missing. Generate token first.")

	headers = {
		"Content-Type": "application/json",
		"ai-api-access-token": settings.api_key,
		"ai-api-refresh-key": settings.refresh_key,
		"Authorization": f"Bearer {settings.access_token}",
		"Referer": settings.referer,
	}

	response = requests.put(f"{settings.base_url}/auth/v2/token", headers=headers, timeout=10)

	data = response.json()

	content = data.get("content", {})

	settings.access_token = content.get("token")
	settings.refresh_key = content.get("refreshKey")

	expiry = datetime.fromtimestamp(int(content.get("validBefore")))
	frappe.log_error(expiry)
	settings.token_expiry = expiry

	settings.save(ignore_permissions=True)

	return "Success"


def get_valid_token():
	settings = frappe.get_single("MyQima Settings")

	if not settings.access_token:
		return __generate_token_manual()

	if not settings.token_expiry:
		return __generate_token_manual()

	now = datetime.now()

	buffer_time = settings.token_expiry - timedelta(minutes=10)

	if now >= buffer_time:
		try:
			frappe.logger().info("Refreshing QIMA token...")
			return __refresh_token_manual()
		except Exception:
			frappe.logger().error("Refresh failed, generating new token...")
			return __generate_token_manual()

	return settings.access_token
