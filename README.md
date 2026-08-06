### Qimaone Integrations

This app bundles **two separate, independent integrations** with QIMA's quality-inspection platforms — they use different QIMA products, different auth models, and different settings doctypes. They are not layers of the same pipeline; either can be used without the other.

| | QIMAone (`qimaone_integrations` module) | MyQima (`myqima` module) |
|---|---|---|
| Settings doctype | **Qima Settings** (single) | **MyQima Settings** (single) |
| Auth | Bearer refresh token, regenerated daily | Access token + refresh key, auto-refreshed 10 min before expiry |
| Transport | CSV file upload to QIMAone's import API | JSON REST API |
| Trigger | Scheduled (every minute dispatcher, gated per-job) | Manual — buttons on Quality Inspection / Quality Request Item |
| Drives | PO import, product upload, inspection report fetch | Ad-hoc inspection booking (create/cancel) |

### QIMAone integration

Pushes Purchase Orders (as draft Quality Inspections) and Items to QIMAone as CSV imports, and pulls back completed inspection reports.

- **PO sync** (`api.append_draft_inspections_to_csv`) — collects draft (`docstatus=0`) Quality Inspections for domestic suppliers (`custom_domestic_supplier=1`) whose Item belongs to an allowed item group (**Qima Settings → Qimaone Allowed item groups**) and whose Supplier is mapped (**Qimaone Supplier Map**). Rows are mapped field-by-field per **Qimaone Supplier Map**/**QIMAone Supplier Template Map**, written into the CSV template at `po_import_file_path`, and POSTed to `po_import_url`.
- **Product sync** (`api.product_uploads`) — same CSV-template approach for Items where `custom_uploaded_on_qima=1`, mapped via **QIMAone Item Template Map**, including EAN barcode as GTIN.
- **Inspection report fetch** (`api.fetch_inspections`) — polls `fetch_inspection_url` for reports with `reportDecision` in `ACCEPTED`/`APPROVED` since `from_date_for_inspection_sync`, then enqueues a background job per report to download the PDF and attach it to the matching Quality Inspection (matched by `purchaseOrderReference` = QC name), setting `custom_inspection_report_status` and submitting the QC.
- **Refresh token** (`api.generate_refresh_token`) — re-authenticates daily using `email_id`/`password`/`api_token` against `refresh_token_url`.
- **PO cancel on QC cancel/delete** — `customizations/quality_inspection/quality_inspection.py` hooks `on_cancel`/`on_trash`: looks the PO up on the QIMA portal by QC name and PATCHes its status to `CANCELLED`.
- **Supplier validation on QC save** — `validate()` blocks saving a Quality Inspection if `enable_supplier_validation` is on, the item's group is in the allowed list, and the supplier isn't present in **QIMAone Supplier Map**.
- Every API call (success or failure) is logged to **QIMA Logs** (status, response body, process ID) via `create_qima_logs`.

**Scheduler** (`schedulers.py`, dispatched every minute by `run_scheduled_syncs`):

| Job | Gate | Interval field | Last-run field |
|---|---|---|---|
| QIMAone PO Sync | always eligible | `no_of_hours` | `last_po_sync` |
| QIMAone Inspection Sync | always eligible | `no_of_hours_for_reports_sync` | `last_inspection_sync` |
| QIMAone Item Sync | `enable_item_sync` checkbox | `no_of_hours_for_item_sync` | `last_item_sync` |

Each job runs only once its configured interval has elapsed since its last run (persisted on **Qima Settings**, so it survives restarts); a failure still advances the timestamp so it doesn't retry every dispatch. `generate_refresh_token` also runs once daily via `hooks.py`'s `daily` scheduler event.

### MyQima integration

A separate, on-demand inspection-booking flow against MyQima's REST API — no scheduler involved.

- **Create booking** — `myqima/customizations/quality_inspection/quality_inspection.py:create_inspection_booking` (button on Quality Inspection) and `myqima/customizations/quality_request/quality_request.py:create_inspection_booking` (button on Quality Request Item row) both POST to `{base_url}/v1.0/inspection`. The category/family/type IDs come from the **Myqima Item Master** child table on the Item; the supplier code comes from `Supplier.custom_myqima_supplier_code` (booking is blocked if the supplier isn't marked `custom_myqima_sync_status`). Booking ID/order number/product ID are written back onto the QC or QR Item row.
- **Cancel booking** — `cancel_inspection_booking` DELETEs `{base_url}/user/{userid}/inspection/{booking_id}` with a reason, then clears the stored booking fields.
- **Auth** (`myqima/utils.py:get_valid_token`) — reuses the cached `access_token` on **MyQima Settings** until 10 minutes before `token_expiry`, then refreshes via `PUT /auth/v2/token`; falls back to a full `POST /auth/v2/token` re-login if refresh fails or no token exists yet.

### Key DocTypes

- **Qima Settings** (single) — QIMAone credentials, CSV template paths, API URLs, sync intervals/toggles, last-run timestamps.
- **MyQima Settings** (single) — MyQima base URL, API key, account credentials, cached access/refresh tokens.
- **QIMAone Item Template Map** / **QIMAone Supplier Template Map** — field-name mapping between ERPNext fields and QIMAone CSV column headers.
- **QIMAone Supplier Map** (`qimaone_overlap`) — ERPNext ↔ QIMAone supplier and supplier-address value overlap, used both to validate and to translate values during CSV export.
- **Qimaone Allowed item groups** — Item Groups eligible for QIMAone PO sync and supplier validation.
- **QIMA Logs** — audit trail of every QIMAone API call (title, status code, response, process ID).
- **Myqima Item Master** (child table on Item) — QIMA category/family/product-type IDs per item, used to build MyQima booking payloads.

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app qimaone_integrations
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/qimaone_integrations
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### License

mit
