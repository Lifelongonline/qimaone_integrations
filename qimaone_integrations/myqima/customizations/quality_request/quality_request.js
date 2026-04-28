frappe.ui.form.on("Quality Request Item", {
	custom_create_inspection: function (frm, cdt, cdn) {
		const row = locals[cdt][cdn];

		// Guard: already booked
		if (row.custom_myqima_inspection_created) {
			frappe.msgprint({
				title: "Already Booked",
				message: `Inspection already created.<br>
					<b>Order Number:</b> ${row.custom_myqima_order_number || "—"}<br>
					<b>Order ID:</b> ${row.custom_myqima_booking_id}`,
				indicator: "blue",
			});
			return;
		}

		if (!frm.doc.name || frm.doc.__islocal) {
			frappe.msgprint({
				title: "Save First",
				message: "Please save the Quality Request before creating an inspection.",
				indicator: "orange",
			});
			return;
		}

		frappe.confirm(
			`Create QIMA inspection booking for <b>${row.item_name || row.item_code}</b>?`,
			() => {
				frappe.dom.freeze("Creating QIMA inspection booking…");

				frappe.call({
					method: "qimaone_integrations.myqima.customizations.quality_request.quality_request.create_inspection_booking",
					args: { qr_item_name: row.name },
					callback: function (r) {
						frappe.dom.unfreeze();

						if (r.exc) return;

						const booking_id = r.message?.booking_id;
						const order_number = r.message?.order_number;

						frm.reload_doc().then(() => {
							frappe.msgprint({
								title: "Inspection Booked",
								message: `
									<b>Order Number:</b> ${order_number}<br>
									<b>Order ID:</b> ${booking_id}
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
});
