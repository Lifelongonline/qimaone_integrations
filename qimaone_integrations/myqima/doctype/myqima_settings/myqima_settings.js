const TOKEN_API = "qimaone_integrations.api.myqima_settings.myqima_settings";

frappe.ui.form.on("MyQima Settings", {
	refresh(frm) {
		frm.add_custom_button("Generate Token", () =>
			update_tokens(frm, "generate_token_manual", "generated")
		);
		frm.add_custom_button("Refresh Token", () =>
			update_tokens(frm, "refresh_token_manual", "refreshed")
		);
	},
});

function update_tokens(frm, method, done) {
	frappe.call({
		method: `${TOKEN_API}.${method}`,
		freeze: true,
		callback(r) {
			frappe.msgprint(`Token ${done} for ${r.message} MyQima login(s).`);
			frm.reload_doc();
		},
	});
}
