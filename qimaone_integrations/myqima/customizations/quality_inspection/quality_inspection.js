frappe.ui.form.on("Quality Inspection", {
	refresh: function (frm) {
		if (frm.doc.__islocal) return;

		frappe.call({
			method: "qimaone_integrations.myqima.customizations.quality_inspection.quality_inspection.can_show_qima_actions",
			args: {
				quality_inspection: frm.doc.name,
			},
			callback: function (r) {
				if (r.message) {
					_render_qima_buttons(frm);
				}
			},
		});
	},
});

// ---------------------------------------------------------------------------
// Helper — MYQIMA fields now live on the single custom_myqima_details child row
// ---------------------------------------------------------------------------

function _get_myqima_row(frm) {
	if (frm.doc.custom_myqima_details && frm.doc.custom_myqima_details.length) {
		return frm.doc.custom_myqima_details[0];
	}
	return {};
}

function _render_qima_buttons(frm) {
	frm.remove_custom_button("MYQIMA Booking Info", "MYQIMA");
	frm.remove_custom_button("Cancel MYQIMA Inspection", "MYQIMA");
	frm.remove_custom_button("Fetch QIMA Report", "MYQIMA");
	frm.remove_custom_button("Re-fetch QIMA Report", "MYQIMA");

	// Only show MYQIMA buttons if import supplier is checked
	if (!frm.doc.custom_import_supplier) return;

	// Bookings are created from the Quality Request, so this form only works with existing ones
	const myqima = _get_myqima_row(frm);
	if (!myqima.myqima_inspection_created) return;

	frm.add_custom_button(
		"MYQIMA Booking Info",
		() => {
			frappe.msgprint({
				title: "MYQIMA Inspection Booked",
				message: `
				<b>Order Number:</b> ${myqima.myqima_order_number || "—"}<br>
				<b>Order ID:</b> ${myqima.myqima_booking_id || "—"}<br>
				<b>Product ID:</b> ${myqima.myqima_product_id || "—"}
				${myqima.myqima_booking_cancelled ? "<br><b>Booking Cancelled</b>" : ""}
			`,
				indicator: myqima.myqima_booking_cancelled ? "red" : "blue",
			});
		},
		"MYQIMA"
	);

	// A cancelled booking keeps its details for reference only
	if (myqima.myqima_booking_cancelled) return;

	// Fetches only this inspection's own product, even when its order is shared with a Quality Request
	if (!myqima.myqima_report_fetched) {
		frm.add_custom_button(
			"Fetch QIMA Report",
			() => {
				_fetch_qima_report(frm);
			},
			"MYQIMA"
		);
	}

	// A report fetched before MyQima had a decision, or that could not be applied, maps
	// nothing until it is fetched again
	if (
		myqima.myqima_report_fetched &&
		(myqima.myqima_decision_pending || myqima.myqima_report_not_applied)
	) {
		frm.add_custom_button(
			"Re-fetch QIMA Report",
			() => {
				_fetch_qima_report(frm);
			},
			"MYQIMA"
		);
	}

	// An order booked through a Quality Request covers all its inspections; cancel it there
	if (frm.doc.custom_quality_request) return;

	frm.add_custom_button(
		"Cancel MYQIMA Inspection",
		() => {
			_show_cancel_dialog(frm);
		},
		"MYQIMA"
	);
}

function _fetch_qima_report(frm) {
	const myqima = _get_myqima_row(frm);

	frappe.confirm(
		`Fetch QIMA report for <b>${myqima.myqima_order_number || frm.doc.name}</b>?`,
		() => {
			frappe.dom.freeze("Fetching QIMA report…");

			frappe.call({
				method: "qimaone_integrations.myqima.customizations.quality_inspection.quality_inspection.fetch_inspection_report",
				args: { quality_inspection_name: frm.doc.name },
				callback: function (r) {
					frappe.dom.unfreeze();
					if (r.exc) return;

					const {
						overall_result,
						report_decision,
						decision_reason,
						report_url,
						inspection_status,
						decision_pending,
					} = r.message;

					frm.reload_doc().then(() => {
						frappe.msgprint({
							title: "QIMA Report Fetched",
							message: `
								<b>Inspection Status:</b> ${inspection_status || "—"}<br>
								<b>Overall Result:</b> ${overall_result || "—"}<br>
								<b>Decision:</b> ${report_decision || "—"}<br>
								${decision_reason ? `<b>Decision Reason:</b> ${frappe.utils.escape_html(decision_reason)}<br>` : ""}
								<b>Report URL:</b> <a href="${report_url}" target="_blank">${report_url || "—"}</a>
								${
									decision_pending
										? "<br><br>The report decision is still pending on MyQima, so nothing was updated on this inspection. Fetch the report again once it is decided."
										: ""
								}
							`,
							indicator: decision_pending
								? "orange"
								: overall_result === "Pass"
								? "green"
								: "red",
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
