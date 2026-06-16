from qimaone_integrations.qimaone_integrations.customizations.quality_inspection.doc_events.utility_functions import (
	cancel_po_on_qima_portal,
	validate_supplier,
)


def on_cancel(doc, event=None):
	cancel_po_on_qima_portal(doc)


def on_trash(doc, event=None):
	if doc.docstatus == 0:  # Only trigger cancellation if the document is in draft state
		cancel_po_on_qima_portal(doc)


def validate(doc, method=None):
	validate_supplier(doc)
