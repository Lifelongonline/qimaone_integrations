frappe.ui.form.on("Quality Request", {
	setup: function (frm) {
		// Address links to Supplier through the Dynamic Link child table, so the
		// standard contacts query is needed here — a plain link filter can't reach it.
		frm.set_query("custom_supplier_address", "quality_request_item", function (doc, cdt, cdn) {
			const row = locals[cdt][cdn];
			return {
				query: "frappe.contacts.doctype.address.address.address_query",
				filters: { link_doctype: "Supplier", link_name: row.supplier },
			};
		});
	},
});

frappe.ui.form.on("Quality Request Item", {
	supplier: function (frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, {
			custom_supplier_address: null,
			custom_sap_supplier_sub_code: null,
		});
	},

	custom_supplier_address: function (frm, cdt, cdn) {
		const row = locals[cdt][cdn];

		if (!row.custom_supplier_address || !row.supplier) {
			frappe.model.set_value(cdt, cdn, "custom_sap_supplier_sub_code", null);
			return;
		}

		frappe.call({
			method: "qimaone_integrations.qimaone_integrations.customizations.quality_request.doc_events.utility_functions.get_supplier_address_sub_code",
			args: { address: row.custom_supplier_address, supplier: row.supplier },
			callback: function (r) {
				frappe.model.set_value(
					cdt,
					cdn,
					"custom_sap_supplier_sub_code",
					r.message || null
				);
			},
		});
	},
});
