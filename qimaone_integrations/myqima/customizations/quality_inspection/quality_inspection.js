frappe.ui.form.on("Quality Inspection", {
	refresh: function (frm) {
		if (frm.doc.__islocal) return;
		_render_qima_buttons(frm);
	},
});

function _render_qima_buttons(frm) {
	frm.remove_custom_button("Create Inspection Booking", "MYQIMA");
	frm.remove_custom_button("MYQIMA Booking Info", "MYQIMA");
	frm.remove_custom_button("Cancel MYQIMA Inspection", "MYQIMA");

	if (frm.doc.custom_myqima_inspection_created) {
		frm.add_custom_button(
			"MYQIMA Booking Info",
			() => {
				frappe.msgprint({
					title: "MYQIMA Inspection Booked",
					message: `
					<b>Order Number:</b> ${frm.doc.custom_myqima_order_number || "—"}<br>
					<b>Order ID:</b> ${frm.doc.custom_myqima_booking_id || "—"}<br>
					<b>Product ID:</b> ${frm.doc.custom_myqima_product_id || "—"}
				`,
					indicator: "blue",
				});
			},
			"MYQIMA"
		);

		// ── Cancel always visible for now (checkbox bypass) ──
		frm.add_custom_button(
			"Cancel MYQIMA Inspection",
			() => {
				_show_cancel_dialog(frm);
			},
			"MYQIMA"
		);
	} else {
		frm.add_custom_button(
			"Create Inspection Booking",
			() => {
				_create_booking(frm);
			},
			"MYQIMA"
		);
	}
}

function _show_cancel_dialog(frm) {
	const d = new frappe.ui.Dialog({
		title: "Cancel MYQIMA Inspection",
		fields: [
			{
				fieldtype: "Select",
				fieldname: "reason",
				label: "Cancellation Reason",
				reqd: 1,
				options: [
					"Customer requested cancellation",
					"Order delayed",
					"Supplier not ready",
					"Wrong booking",
					"Other",
				].join("\n"),
				default: "Customer requested cancellation",
			},
			{
				fieldtype: "Small Text",
				fieldname: "reason_options",
				label: "Additional Details (optional)",
			},
		],
		primary_action_label: "Confirm Cancellation",
		primary_action(values) {
			d.hide();
			frappe.dom.freeze("Cancelling MYQIMA inspection…");

			frappe.call({
				method: "qimaone_integrations.myqima.customizations.quality_inspection.quality_inspection.cancel_inspection_booking",
				args: {
					quality_inspection_name: frm.doc.name,
					reason: values.reason,
					reason_options: values.reason_options || "",
				},
				callback: function (r) {
					frappe.dom.unfreeze();
					if (r.exc) return;

					frm.reload_doc().then(() => {
						frappe.msgprint({
							title: "Inspection Cancelled",
							message: "MYQIMA inspection booking has been successfully cancelled.",
							indicator: "green",
						});
					});
				},
				error: function () {
					frappe.dom.unfreeze();
				},
			});
		},
	});

	d.show();
}

function _create_booking(frm) {
	frappe.confirm(
		`Create MYQIMA inspection booking for <b>${frm.doc.item_name || frm.doc.item_code}</b>?`,
		() => {
			frappe.dom.freeze("Creating MYQIMA inspection booking…");

			frappe.call({
				method: "qimaone_integrations.myqima.customizations.quality_inspection.quality_inspection.create_inspection_booking",
				args: { quality_inspection_name: frm.doc.name },
				callback: function (r) {
					frappe.dom.unfreeze();
					if (r.exc) return;

					const { booking_id, order_number, product_id } = r.message;

					frm.reload_doc().then(() => {
						frappe.msgprint({
							title: "Inspection Booked",
							message: `
								<b>Order Number:</b> ${order_number}<br>
								<b>Order ID:</b> ${booking_id}<br>
								<b>Product ID:</b> ${product_id}
							`,
							indicator: "green",
						});
					});
				},
				error: function () {
					frappe.dom.unfreeze();
				},
			});
		}
	);
}
