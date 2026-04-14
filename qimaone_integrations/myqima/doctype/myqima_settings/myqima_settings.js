frappe.ui.form.on("MyQima Settings", {
	refresh(frm) {
		frm.add_custom_button("Generate Token", function () {
			frappe.call({
				method: "qimaone_integrations.api.myqima_settings.myqima_settings.generate_token_manual",
				callback: function (r) {
					frappe.msgprint("Token Generated Successfully");
					frm.reload_doc();
				},
			});
		});

		frm.add_custom_button("Refresh Token", function () {
			frappe.call({
				method: "qimaone_integrations.api.myqima_settings.myqima_settings.refresh_token_manual",
				callback: function (r) {
					frappe.msgprint("Token Refreshed Successfully");
					frm.reload_doc();
				},
			});
		});
	},
});
