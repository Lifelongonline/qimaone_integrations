# Copyright (c) 2026, gopal@8848digital.com and contributors
# For license information, please see license.txt

import frappe

from qimaone_integrations.myqima.doctype.myqima_error_log.myqima_error_log import get_open_error_summaries
from qimaone_integrations.myqima.utils import api_response


@frappe.whitelist(methods=["GET"])
def get_open_myqima_errors(quality_request: str):
	"""
	Return the open MyQima Error Logs of a Quality Request, shown as a warning on its form.
	Only answers for a Quality Request the user can read, and only with logs the user can read.

	**Endpoint:** `/api/method/qimaone_integrations.myqima.api.v1.quality_request.get_open_myqima_errors`
	**HTTP Method:** GET
	**Parameters:**
		- quality_request (str, required): name of the Quality Request, e.g. "QR26-27-00133"
	**Response:**
```json
		{
			"status": true,
			"status_code": 200,
			"message": "1 open MyQima error(s)",
			"data": [
				{
					"name": "MYQIMA-ERR-2026-00001",
					"job": "Inspection Booking",
					"summary": "All rows booked together must have the same QC Date.",
					"last_seen": "2026-10-21 12:00:00",
					"occurrences": 3
				}
			],
			"errors": null
		}
```
	"""
	logs = get_open_error_summaries(quality_request)
	return api_response(message=f"{len(logs)} open MyQima error(s)", data=logs)
