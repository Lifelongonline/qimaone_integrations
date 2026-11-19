# myqima

## Purpose

Owns the MyQima integration: booking MyQima inspections for Quality Requests, fetching their
reports onto Quality Inspections, cancelling bookings, and the scheduler that does booking and
report fetch automatically (`tasks.py`).

## DocTypes

| DocType | Purpose |
| ------- | ------- |
| MyQima Settings | Connection, allowed item groups, logins per item group, report handling and scheduler settings. |
| MyQima Error Log | Problems the scheduler hit, one open log per Quality Request and job. |
| MyQima API Log | Every call made to MyQima, with request and response. |
| MyQima Details | Child of Quality Inspection: the inspection's booking, status and report. |
| MyQima Item Master | Child of Item: the item's MyQima data. |
| QIMA Category Credentials | Child of MyQima Settings: the MyQima login and token for one item group. |

## Customizations

| DocType | Owned by | What's customized |
| ------- | -------- | ------------------ |
| Quality Request | Lifelong DSR Customization | Create / fetch / cancel MyQima booking buttons, open error warning, cancel blocked while a booking is active. *Push Consolidated Items in MyQima Portal* books the rows as one product with each item as a reference, for one report (at most 10 items), and maps each inspection from the decision of its own SKU in that report; unchecked, each item is its own product with its own report. Saving is refused above the SKU limit in MyQima Settings, when that check is on. |
| Quality Inspection | ERPNext | Booking info / fetch / cancel buttons, cancel blocked while its booking is active. |
