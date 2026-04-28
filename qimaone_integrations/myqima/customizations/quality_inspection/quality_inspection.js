frappe.ui.form.on("Quality Inspection", {
	refresh: function (frm) {
		if (frm.doc.__islocal) return;

		_render_qima_buttons(frm);
	},
});

function _render_qima_buttons(frm) {
	// Remove existing QIMA buttons to avoid duplicates on re-render
	frm.remove_custom_button("Create Inspection Booking", "QIMA");
	frm.remove_custom_button("QIMA Booking Info", "QIMA");
	frm.remove_custom_button("Cancel QIMA Inspection", "QIMA");

	if (frm.doc.custom_myqima_inspection_created) {
		// ── Already booked ──────────────────────────────────────────
		frm.add_custom_button(
			"QIMA Booking Info",
			() => {
				frappe.msgprint({
					title: "QIMA Inspection Booked",
					message: `
					<b>Order Number:</b> ${frm.doc.custom_myqima_order_number || "—"}<br>
					<b>Order ID:</b> ${frm.doc.custom_myqima_booking_id || "—"}<br>
					<b>Product ID:</b> ${frm.doc.custom_myqima_product_id || "—"}
				`,
					indicator: "blue",
				});
			},
			"QIMA"
		);

		// Cancel button only visible when checkbox is checked
		if (frm.doc.custom_myqima_cancel_inspection) {
			frm.add_custom_button(
				"Cancel QIMA Inspection",
				() => {
					_show_cancel_dialog(frm);
				},
				"QIMA"
			);

			// Highlight cancel button in red
			frm.page.inner_toolbar
				.find(`[data-label="Cancel QIMA Inspection"]`)
				.addClass("btn-danger")
				.removeClass("btn-default");
		}
	} else {
		// ── Not yet booked ───────────────────────────────────────────
		frm.add_custom_button(
			"Create Inspection Booking",
			() => {
				_create_booking(frm);
			},
			"QIMA"
		);
	}
}

function _show_cancel_dialog(frm) {
	const d = new frappe.ui.Dialog({
		title: "Cancel QIMA Inspection",
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
			frappe.dom.freeze("Cancelling QIMA inspection…");

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
							message: "QIMA inspection booking has been successfully cancelled.",
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
		`Create QIMA inspection booking for <b>${frm.doc.item_name || frm.doc.item_code}</b>?`,
		() => {
			frappe.dom.freeze("Creating QIMA inspection booking…");

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
