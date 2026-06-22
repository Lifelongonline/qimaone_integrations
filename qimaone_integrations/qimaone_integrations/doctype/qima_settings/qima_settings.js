// Copyright (c) 2026, gopal@8848digital.com and contributors
// For license information, please see license.txt

frappe.ui.form.on("Qima Settings", {
	refresh(frm) {
		frm.events.create_refresh_buttons(frm);
		frm.events.create_po_button(frm);
		frm.events.download_inspections_button(frm);
		frm.events.create_product_button(frm);
	},
	create_refresh_buttons(frm) {
		frm.add_custom_button(__("Generate Refresh Token"), function () {
			if (!frm.doc.email_id || !frm.doc.password || !frm.doc.api_token) {
				frappe.msgprint(
					__(
						"Please fill in Email ID, Password, and API Token before generating the refresh token."
					)
				);
				return;
			}
			frappe.call({
				method: "qimaone_integrations.qimaone_integrations.doctype.qima_settings.api.api.generate_refresh_token",
				callback: function (r) {
					const msg = r.message == "Success" ? true : false;
					if (msg) {
							frm.reload_doc();
							frappe.msgprint(__("Refresh token generated and saved successfully."));
						} 
					},
				});
		});
	},
	create_po_button(frm) {
		frm.add_custom_button(__("Create PO in QIMAone"), function () {
			if (!frm.doc.default_qima_uom) {
				frappe.throw(
					__(frappe.throw("Please set the Default QIMA UOM before creating the PO."))
				);
			}
			frappe.call({
				method: "qimaone_integrations.qimaone_integrations.doctype.qima_settings.api.api.append_draft_inspections_to_csv",
				args: {
					token: frm.doc.refresh_token,
					import_po_url: frm.doc.po_import_url,
					unit: frm.doc.default_qima_uom,
				},
				freeze: true,
				freeze_message: __("Creating Purchase Orders in QIMAOne..."),
				callback: function (r) {
					frappe.msgprint(
						__(
							"Purchase Orders sent to QIMAOne successfully. For more details please check QIMA Logs."
						)
					);
				},
			});
		});
	},
	download_inspections_button(frm) {
		if (!frm.doc.from_date_for_inspection_sync) {
			frappe.throw(
				__(
					frappe.throw(
						"Please set the From Date for Inspection Sync before downloading the inspection reports."
					)
				)
			);
			return;
		}
		frm.add_custom_button(__("Get Inspection Report from Qimaone"), function () {
			frappe.call({
				method: "qimaone_integrations.qimaone_integrations.doctype.qima_settings.api.api.fetch_inspections",
				freeze: true,
				freeze_message: __("Fetching Inspection Reports from QIMAOne..."),
			});
		});
	},
	create_product_button(frm) {
		frm.add_custom_button(__("Create Product in QIMAone"), function () {
			if (!frm.doc.default_qima_uom) {
				frappe.throw(
					__(
						frappe.throw(
							"Please set the Default QIMA UOM before creating the Product."
						)
					)
				);
			}
			frappe.call({
				method: "qimaone_integrations.qimaone_integrations.doctype.qima_settings.api.api.product_uploads",
				args: {
					token: frm.doc.refresh_token,
					import_product_url: frm.doc.product_import_url,
					unit: frm.doc.default_qima_uom,
				},
				freeze: true,
				freeze_message: __("Creating Products in QIMAOne..."),
				callback: function (r) {
					frappe.msgprint(
						__(
							"Products sent to QIMAOne successfully. For more details please check QIMA Logs."
						)
					);
				},
			});
		});
	},
});
