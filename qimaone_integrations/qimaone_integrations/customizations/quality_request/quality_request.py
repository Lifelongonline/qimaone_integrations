from qimaone_integrations.qimaone_integrations.customizations.quality_request.doc_events.utility_functions import (
	set_sap_supplier_sub_code,
)


def validate(doc, method=None):
	set_sap_supplier_sub_code(doc)
