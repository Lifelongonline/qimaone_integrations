// Copyright (c) 2026, gopal@8848digital.com and contributors
// For license information, please see license.txt

frappe.ui.form.on("QIMA Logs", {
	refresh(frm) {
		frm.events.fetch_process_status(frm);
	},
	fetch_process_status(frm) {
		if (frm.doc.process_id) {
			frm.add_custom_button(__("Fetch Process Status"), function () {
				frappe.call({
					method: "qimaone_integrations.qimaone_integrations.doctype.qima_settings.api.api.fetch_process_status",
					args: {
						process_id: frm.doc.process_id,
					},
					freeze: true,
					freeze_message: __("Fetching Process Status..."),
					callback: function (response) {
						if (response) {
							frm.set_value("process_response", JSON.stringify(response));
							frm.save().then(() => {
								frappe.msgprint(
									__("Process status fetched and saved successfully.")
								);
							});
						}
					},
				});
			});
		}
	},
});
