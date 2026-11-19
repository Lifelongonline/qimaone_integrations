# SETUP.md

## MyQima

### Overview

Books MyQima inspections for import-supplier Quality Requests and fetches their reports back
onto the Quality Inspections, from the form buttons or on a schedule.

### Required Credentials

| Credential | Where it's stored | Required? |
| ---------- | ------------------ | --------- |
| API Key (`ai-api-access-token`) | MyQima Settings → `api_key` | Yes |
| Referer | MyQima Settings → `referer` | Yes |
| MyQima login and password, per item group | MyQima Settings → MYQIMA Category Credentials → `account`, `password` | Yes |

The password is stored encrypted, as the MD5 hash MyQima expects. Saving MyQima Settings logs each
new or changed login in and fills its User ID, access token, refresh key and expiry; a wrong login
stops the save. The access token and refresh key are hidden on the form, and masked in MyQima API
Log. **Generate Token** logs every row in again and **Refresh Token** refreshes every row's token;
both are for System Managers only. Tokens are also refreshed on their own before they expire.

### Settings DocType Fields (MyQima Settings)

| Field | Type | Mandatory | Notes |
| ----- | ---- | --------- | ----- |
| Base URL | Data | Yes | MyQima API base URL. |
| API Key | Data | Yes | See Required Credentials. |
| Referer | Data | Yes | See Required Credentials. |
| MYQIMA Allowed Item Group | Table | Yes | Item groups whose inspections can be booked. |
| MYQIMA Category Credentials | Table | Yes | One row per item group: ERPNext category, MyQima login and password. |
| Quality Inspection Status | Select | No | Submitted: an accepted report submits its Quality Inspection. |
| Auto Update Inspection Result | Check | No | Sets the inspection status and Accepted or Rejected Qty from the report. |
| Update Result Based On | Select | When Auto Update Inspection Result is on | MyQima Overall Result or MyQima Report Decision. With Report Decision, a pending decision leaves the inspection untouched (no status, quantities or PDF) and the report is fetched again — by the scheduler or MYQIMA → Re-fetch QIMA Report — until decided; Accepted sets the produced quantity as Accepted Qty, Rejected as Rejected Qty. A consolidated booking (Push Consolidated Items in MyQima Portal) always uses the report decision of each inspection's own SKU, whatever this says, with its booked quantity as Accepted or Rejected Qty. |
| Validate SKU qty for QR creation | Check | No | Stops a Quality Request from being saved or submitted with more MyQima rows than the limit below. Only rows of an import supplier whose item group is in MYQIMA Allowed Item Group are counted. |
| No of SKU per Quality Request | Int | When Validate SKU qty for QR creation is on | At least 1. |
| Sync From Date (QR Posting Date) | Date | When a scheduler job is enabled | Both scheduler jobs only pick Quality Requests posted on or after this date. |
| Enable Auto Inspection Booking | Check | No | Books submitted import-supplier Quality Requests never booked before that have a row in MYQIMA Allowed Item Group; others are skipped without an error. Cancelled bookings are not booked again. |
| Inspection Booking Interval (Minutes) | Int | When auto booking is enabled | At least 1. |
| Enable Auto Report Fetch | Check | No | Fetches the reports of active bookings not fetched yet, whose report decision is pending, or that could not be applied (an unknown result, a produced quantity above Offered Qty or a failed submit). Those are listed in MyQima Error Log and fetched again until they apply. |
| Report Fetch Interval (Minutes) | Int | When auto report fetch is enabled | At least 1. |
| Last Booking Run / Last Report Fetch Run | Datetime | Read only | When each job last started. |

### Other requirements

- **Supplier sub code:** every Quality Request row must have its SAP Supplier Sub Code; a booking
  sends it as the supplier code and refuses rows without one.
- **Scheduler:** both jobs are checked every minute and run on the `long` queue, so the site
  needs the scheduler enabled and a worker on the long queue.
- **Role:** assign **MyQima Booking Cancel Bypass** only to users allowed to cancel a Quality
  Request or Quality Inspection while its MyQima booking is still active.
- **Error list:** System Managers and Quality Managers can read and resolve MyQima Error Logs.

### How to Test

1. Save MyQima Settings with a Category Credentials row: the save logs in and fills User ID.
2. On a submitted import-supplier Quality Request, use MYQIMA → Create Inspection Booking and
   check MyQima API Log for the Inspection Booking call.
3. Set Sync From Date, enable auto booking with an interval of 1 minute, and check that Last
   Booking Run updates within a couple of minutes; anything that cannot be booked shows up in
   MyQima Error Log and on its Quality Request.
