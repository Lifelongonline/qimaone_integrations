import hashlib
import json
import re
import time
from contextlib import contextmanager
from datetime import datetime, timedelta

import frappe
import requests
from redis.exceptions import LockError

# Keys whose string values are masked before a request or response is written to MyQima API Log
SENSITIVE_KEYS = {"password", "token", "refreshKey"}

# MyQima passwords are sent as an MD5 hash: 32 lowercase hexadecimal characters
MD5_HEX = re.compile(r"[0-9a-f]{32}")

# Users with this role may cancel a Quality Request or Quality Inspection whose MyQima booking is still active
BOOKING_CANCEL_BYPASS_ROLE = "MyQima Booking Cancel Bypass"

# A lock expires on its own after this many seconds, so a crashed worker cannot hold it forever.
# Long enough for a booking, or a report fetch downloading several PDFs, to finish.
LOCK_EXPIRY = 600


class MyQimaBusyError(frappe.ValidationError):
	"""Another worker or user is already working on the same MyQima booking."""


class MyQimaReportUpdateError(frappe.ValidationError):
	"""A fetched MyQima report could not be applied to its Quality Inspection; it is fetched again until it applies."""


def api_response(status: bool = True, code: int = 200, message: str = "", data=None, errors=None) -> dict:
	"""
	Build the standard response envelope returned by the myqima/api endpoints.

	Args:
		status (bool, optional): success or failure. Default True.
		code (int, optional): HTTP status code. Default 200.
		message (str, optional): human-readable message, safe to show to a user.
		data (object/array/None, optional): payload on success.
		errors (object/array/None, optional): error detail on failure.

	Returns:
		dict: {"status", "status_code", "message", "data", "errors"}
	"""
	return {
		"status": status,
		"status_code": code,
		"message": message,
		"data": data,
		"errors": errors,
	}


@contextmanager
def myqima_lock(key, wait=0):
	"""
	Hold a Redis lock while working on one MyQima booking, shared across all workers and users.

	The scheduler, the form buttons and cancellation all take the lock of the same Quality
	Request (or Quality Inspection, for one booked on its own), so two of them can never book,
	fetch or cancel the same booking at once. Redis is used rather than a database row lock so
	no database lock is held while waiting on QIMA.

	Args:
		key (str): what is locked, e.g. a Quality Request name
		wait (int): seconds to wait for the lock; 0 fails at once

	Raises:
		MyQimaBusyError: when the lock is still held after waiting
	"""
	lock = frappe.cache.lock(frappe.cache.make_key(f"myqima_lock:{key}"), timeout=LOCK_EXPIRY)
	if not lock.acquire(blocking=bool(wait), blocking_timeout=wait or None):
		raise MyQimaBusyError(
			f"MyQima is already processing <b>{key}</b>. Please try again in a minute."
		)

	try:
		yield
	finally:
		try:
			lock.release()
		except LockError:
			# Expired after LOCK_EXPIRY, and possibly taken by someone else since: nothing to release
			pass


def can_bypass_booking_check():
	"""Return True when the role that skips the active booking cancel check is assigned to the current user.

	Reads the user's own Has Role rows rather than frappe.get_roles(), which hands Administrator
	every role, so Administrator is checked like any other user.
	"""
	return bool(
		frappe.db.exists(
			"Has Role",
			{"parent": frappe.session.user, "parenttype": "User", "role": BOOKING_CANCEL_BYPASS_ROLE},
		)
	)


def call_myqima_api(api, method, url, reference=None, booking_id=None, log_response=True, **request_kwargs):
	"""
	Send a request to MyQima and record it in MyQima API Log.

	Returns the response whatever its status code; a network error is logged and re-raised.

	Args:
		api (str): one of the API options on MyQima API Log e.g. 'Inspection Booking'
		method (str): HTTP method
		url (str): full request URL
		reference (Document): document the call was made for, linked on the log
		booking_id (str): MyQima order ID, if the call is about an existing booking
		log_response (bool): False for binary downloads, which log only their type and size
		**request_kwargs: passed on to requests.request (headers, json, params, timeout)
	"""
	values = {
		"doctype": "MyQima API Log",
		"api": api,
		"method": method,
		"url": url,
		"reference_doctype": reference.doctype if reference else None,
		"reference_name": reference.name if reference else None,
		"booking_id": booking_id,
		"request_payload": _to_log_json(request_kwargs.get("json") or request_kwargs.get("params")),
	}
	started = time.monotonic()

	try:
		response = requests.request(method, url, **request_kwargs)
	except requests.exceptions.RequestException as exc:
		values.update(status="Failed", error=str(exc), response_time=time.monotonic() - started)
		_insert_api_log(values)
		raise

	values.update(
		status="Success" if response.ok else "Failed",
		status_code=response.status_code,
		response_time=time.monotonic() - started,
		response=_response_for_log(response, log_response),
		booking_id=booking_id or (log_response and _order_id_from(response)) or None,
	)
	_insert_api_log(values)

	return response


def _order_id_from(response):
	"""Return the MyQima order ID a response carries, so a new booking's log can be found by it."""
	try:
		return ((response.json().get("content") or {}).get("orderGeneralInfo") or {}).get("orderId")
	except (ValueError, AttributeError):
		return None


def _response_for_log(response, log_response):
	"""Return the response body as masked JSON, as text if it is not JSON, or a size note for downloads."""
	if not log_response:
		return _to_log_json(
			{"content_type": response.headers.get("Content-Type"), "bytes": len(response.content)}
		)

	try:
		return _to_log_json(response.json())
	except ValueError:
		return response.text


def _to_log_json(data):
	"""Serialise request or response data for the log, masking passwords and tokens."""
	if data is None:
		return None
	return json.dumps(_mask_sensitive(data), indent=2, default=str)


def _mask_sensitive(data):
	"""Return a copy of data with the string values of SENSITIVE_KEYS replaced by '***'."""
	if isinstance(data, dict):
		return {
			key: "***" if key in SENSITIVE_KEYS and isinstance(value, str) else _mask_sensitive(value)
			for key, value in data.items()
		}
	if isinstance(data, list):
		return [_mask_sensitive(value) for value in data]
	return data


def _insert_api_log(values):
	"""
	Insert a MyQima API Log that survives the request being rolled back.

	Most failed calls end in frappe.throw, which rolls the transaction back and would take the
	log with it. Logs written since the last commit are therefore kept aside and inserted again
	once a rollback has happened. A commit makes that unnecessary, so it clears them.
	"""
	frappe.get_doc(values).insert(ignore_permissions=True)

	pending = frappe.flags.setdefault("myqima_api_logs", [])
	if not pending:
		frappe.db.after_rollback.add(_reinsert_rolled_back_logs)
		frappe.db.after_commit.add(pending.clear)
	pending.append(values)


def _reinsert_rolled_back_logs():
	"""Insert again the MyQima API Logs undone by a rollback, and commit them on their own."""
	for values in frappe.flags.pop("myqima_api_logs", []):
		frappe.get_doc(values).insert(ignore_permissions=True)
	frappe.db.commit()


def get_headers(settings, token):
	"""Return the headers QIMA expects on an authenticated request."""
	return {
		"Content-Type": "application/json",
		"Ai-Api-Access-Token": settings.api_key,
		"Referer": settings.referer,
		"Authorization": f"Bearer {token}",
		"Connection": "keep-alive",
	}


def get_category_credentials(item_group):
	"""Return the MyQima Category Credentials child row mapped to the given Item Group."""
	settings = frappe.get_single("MyQima Settings")

	for row in settings.myqima_category_credentials:
		if row.erpnext_category == item_group:
			return row

	frappe.throw(
		f"No MyQima Category Credentials configured for Item Group <b>{item_group}</b>. "
		f"Please add a row in MyQima Settings before creating an inspection booking."
	)


def to_md5_password(password):
	"""Return the MD5 hash MyQima expects as a password; a value that already is one is kept as is."""
	if MD5_HEX.fullmatch(password):
		return password
	return hashlib.md5(password.encode()).hexdigest()


def request_token(settings, account, password_hash):
	"""
	Log in to MyQima and return the response content, holding "token" and "user".

	Throws with a readable message when MyQima cannot be reached, refuses the login, or
	returns no token.

	Args:
		settings (Document): MyQima Settings, for the base URL, API key and referer
		account (str): MyQima login e.g. 'API.26.08.17.03'
		password_hash (str): the MD5-hashed password
	"""
	try:
		response = call_myqima_api(
			"Generate Token",
			"POST",
			f"{settings.base_url}/auth/v2/token",
			reference=settings,
			headers={
				"Content-Type": "application/json",
				"ai-api-access-token": settings.api_key,
				"Referer": settings.referer,
			},
			json={
				"account": account,
				"password": password_hash,
				"userType": "client",
				"tokenExpire": "3600",
			},
			timeout=30,
		)
	except requests.exceptions.RequestException as exc:
		frappe.throw(f"Could not reach MyQima to log in <b>{account}</b>:<br>{exc}")

	if not response.ok:
		frappe.throw(
			f"MyQima login failed for <b>{account}</b>. Please check the login and password.<br>"
			f"Response: {response.text}"
		)

	content = response.json().get("content") or {}
	token = content.get("token") or {}
	if not token.get("token") or not token.get("validBefore"):
		frappe.throw(
			f"MyQima login for <b>{account}</b> returned no token. See MyQima API Log for the response."
		)

	return content


def __generate_token_manual(settings, cred_row):
	token_data = request_token(settings, cred_row.account, cred_row.get_password("password"))["token"]

	access_token = token_data.get("token")
	refresh_key = token_data.get("refreshKey")
	token_expiry = datetime.fromtimestamp(int(token_data.get("validBefore")))

	frappe.db.set_value(
		"QIMA Category Credentials",
		cred_row.name,
		{
			"access_token": access_token,
			"refresh_key": refresh_key,
			"token_expiry": token_expiry,
		},
		update_modified=False,
	)
	frappe.db.commit()

	cred_row.access_token = access_token
	cred_row.refresh_key = refresh_key
	cred_row.token_expiry = token_expiry

	frappe.logger().info(f"[QIMA] New token generated successfully for account {cred_row.account}.")

	return access_token


def __refresh_token_manual(settings, cred_row):
	if not cred_row.access_token or not cred_row.refresh_key:
		raise Exception("Token or Refresh Key missing — cannot refresh.")

	headers = {
		"Content-Type": "application/json",
		"ai-api-access-token": settings.api_key,
		"ai-api-refresh-key": cred_row.refresh_key,
		"Authorization": f"Bearer {cred_row.access_token}",
		"Referer": settings.referer,
	}

	response = call_myqima_api(
		"Refresh Token",
		"PUT",
		f"{settings.base_url}/auth/v2/token",
		reference=settings,
		headers=headers,
		timeout=10,
	)

	if not response.ok:
		raise Exception(f"Refresh failed: {response.status_code} — {response.text}")

	data = response.json()
	content = data.get("content", {})

	token = content.get("token")
	valid_before = content.get("validBefore")

	if not token or not valid_before:
		raise Exception(f"Refresh response missing token data: {_to_log_json(data)}")

	access_token = token
	refresh_key = content.get("refreshKey")
	token_expiry = datetime.fromtimestamp(int(valid_before))

	frappe.db.set_value(
		"QIMA Category Credentials",
		cred_row.name,
		{
			"access_token": access_token,
			"refresh_key": refresh_key,
			"token_expiry": token_expiry,
		},
		update_modified=False,
	)
	frappe.db.commit()

	cred_row.access_token = access_token
	cred_row.refresh_key = refresh_key
	cred_row.token_expiry = token_expiry

	frappe.logger().info(f"[QIMA] Token refreshed successfully for account {cred_row.account}.")

	return access_token


def get_valid_token(cred_row):
	"""
	Return a usable access token for a Category Credentials row, refreshing or regenerating it.

	The booking and report jobs can ask for the same row's token at the same moment. A refresh
	replaces the refresh key, so two refreshes at once would leave one of them with a dead token.
	The lock makes them take turns, and the token is read again inside it so the second one uses
	the token the first one just saved instead of refreshing again.
	"""
	with token_lock(cred_row):
		return _get_valid_token(cred_row)


@contextmanager
def token_lock(cred_row):
	"""Hold a Category Credentials row's token lock, with its token read again from the database."""
	with myqima_lock(f"token:{cred_row.name}", wait=60):
		cred_row.update(
			frappe.db.get_value(
				"QIMA Category Credentials",
				cred_row.name,
				["access_token", "refresh_key", "token_expiry"],
				as_dict=True,
			)
			or {}
		)
		yield


def _get_valid_token(cred_row):
	"""Return the row's token, refreshing it near expiry and generating a new one if refresh fails."""
	settings = frappe.get_single("MyQima Settings")

	if not cred_row.access_token or not cred_row.token_expiry:
		frappe.logger().info(f"[QIMA] No token/expiry found for {cred_row.account} — generating new token.")
		return __generate_token_manual(settings, cred_row)

	now = datetime.now()

	token_expiry = cred_row.token_expiry
	if isinstance(token_expiry, str):
		token_expiry = datetime.strptime(token_expiry[:19], "%Y-%m-%d %H:%M:%S")

	buffer_time = token_expiry - timedelta(minutes=10)

	if now >= buffer_time:
		try:
			frappe.logger().info(
				f"[QIMA] Token near/past expiry for {cred_row.account} — attempting refresh."
			)
			return __refresh_token_manual(settings, cred_row)
		except Exception as e:
			frappe.logger().warning(f"[QIMA] Refresh failed ({e}) — generating new token.")
			return __generate_token_manual(settings, cred_row)

	return cred_row.access_token
