frappe.ui.form.on("Quality Inspection", {
	refresh: function (frm) {
		// Don't show button on new unsaved docs
		if (frm.doc.__islocal) return;

		if (frm.doc.custom_myqima_inspection_created) {
			// Already booked — show read-only info button
			frm.add_custom_button(
				"QIMA Booking Info",
				() => {
					frappe.msgprint({
						title: "QIMA Inspection Already Booked",
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
		} else {
			frm.add_custom_button(
				"Create Inspection Booking",
				() => {
					frappe.confirm(
						`Create QIMA inspection booking for <b>${
							frm.doc.item_name || frm.doc.item_code
						}</b>?`,
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
				},
				"QIMA"
			);
		}
	},
});
