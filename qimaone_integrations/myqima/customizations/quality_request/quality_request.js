frappe.ui.form.on("Quality Request", {
	refresh: function (frm) {
		if (frm.doc.docstatus === 0) return;

		frappe.call({
			method: "qimaone_integrations.myqima.customizations.quality_request.quality_request.get_myqima_bookings",
			args: { quality_request_name: frm.doc.name },
			callback: function (r) {
				_render_qr_myqima_buttons(frm, r.message || []);
			},
		});

		_show_open_myqima_errors(frm);
	},
});

/**
 * Show the open MyQima Error Logs of the request as a red headline on its form, one line each
 * with a link to the log, so users see what the scheduler could not do without opening the log.
 *
 * @param {object} frm - the Quality Request form
 */
function _show_open_myqima_errors(frm) {
	frappe.call({
		method: "qimaone_integrations.myqima.api.v1.quality_request.get_open_myqima_errors",
		type: "GET",
		args: { quality_request: frm.doc.name },
		callback: function (r) {
			const logs = (r.message && r.message.data) || [];
			if (!logs.length) return;

			const escape = frappe.utils.escape_html;
			const lines = logs
				.map((log) => {
					const href = `/app/myqima-error-log/${encodeURIComponent(log.name)}`;
					const link = `<a href="${href}">${escape(log.name)}</a>`;
					return `<b>MyQima ${escape(log.job)} failed</b> (${link}): ${escape(log.summary)}`;
				})
				.join("<br>");

			frm.dashboard.set_headline_alert(lines, "red");
		},
	});
}

// Columns of the tables that show each booked row with its MyQima report
const REPORT_COLUMNS = [
	["Row", "idx"],
	["Item", "item_code"],
	["Quality Inspection", "quality_inspection"],
	["Order Number", "order_number"],
	["Status", "inspection_status"],
	["Overall Result", "overall_result"],
	["Decision", "report_decision"],
	["Decision Reason", "decision_reason"],
];

function _render_qr_myqima_buttons(frm, rows) {
	frm.remove_custom_button("Create Inspection Booking", "MYQIMA");
	frm.remove_custom_button("MYQIMA Booking Info", "MYQIMA");
	frm.remove_custom_button("Fetch MYQIMA Report", "MYQIMA");
	frm.remove_custom_button("Cancel MYQIMA Inspection", "MYQIMA");

	const bookable = rows.filter((row) => row.eligible && !row.booked);
	const booked = rows.filter((row) => row.booked);
	// Not fetched yet, or fetched before MyQima had a report decision
	const unfetched = booked.filter((row) => row.report_due);

	if (frm.doc.docstatus === 1 && bookable.length) {
		frm.add_custom_button(
			"Create Inspection Booking",
			() => _create_qr_booking(frm, rows),
			"MYQIMA"
		);
	}

	if (!booked.length) return;

	frm.add_custom_button("MYQIMA Booking Info", () => _show_qr_booking_info(booked), "MYQIMA");

	if (unfetched.length) {
		frm.add_custom_button(
			"Fetch MYQIMA Report",
			() => _fetch_qr_report(frm, unfetched),
			"MYQIMA"
		);
	}

	frm.add_custom_button("Cancel MYQIMA Inspection", () => _show_qr_cancel_dialog(frm), "MYQIMA");
}

function _rows_table(rows, columns) {
	const head = columns.map(([label]) => `<th>${label}</th>`).join("");
	const cell = (value) => `<td>${frappe.utils.escape_html(String(value || "—"))}</td>`;
	const body = rows
		.map((row) => `<tr>${columns.map(([, key]) => cell(row[key])).join("")}</tr>`)
		.join("");

	// Long IDs stay on one line; the wrapper scrolls sideways instead of spilling out of the dialog
	return `<div class="table-responsive">
		<table class="table table-bordered table-sm" style="white-space: nowrap; margin: 0;">
			<thead><tr>${head}</tr></thead><tbody>${body}</tbody>
		</table>
	</div>`;
}

function _create_qr_booking(frm, rows) {
	const pending = rows.filter((row) => !row.booked);
	const not_eligible = pending.filter((row) => !row.eligible);

	// Every unbooked row must go into the booking; the server refuses otherwise, so say why up front
	if (not_eligible.length) {
		frappe.msgprint({
			title: "Rows Cannot Be Booked",
			message: `No booking was created. Every row must be eligible for MYQIMA:<br><br>${_rows_table(
				not_eligible,
				[
					["Row", "idx"],
					["Item", "item_code"],
					["Quality Inspection", "quality_inspection"],
					["Reason", "not_eligible_reason"],
				]
			)}`,
			indicator: "red",
			wide: true,
		});
		return;
	}

	const table = _rows_table(pending, [
		["Row", "idx"],
		["Item", "item_code"],
		["Quality Inspection", "quality_inspection"],
		["QC Qty", "qc_qty"],
	]);

	// Consolidated, the rows go as one product with one report; otherwise each row is its own product
	const booking = frm.doc.custom_push_consolidated_items_in_myqima
		? "one consolidated MYQIMA inspection booking (one product, one report)"
		: "one MYQIMA inspection booking";

	frappe.confirm(`Create ${booking} for these rows?<br><br>${table}`, () => {
		frappe.dom.freeze("Creating MYQIMA inspection booking…");

		frappe.call({
			method: "qimaone_integrations.myqima.customizations.quality_request.quality_request.create_inspection_booking",
			args: { quality_request_name: frm.doc.name },
			callback: function (r) {
				frappe.dom.unfreeze();
				if (r.exc) return;

				const { booking_id, order_number, inspections } = r.message;

				frm.reload_doc().then(() => {
					frappe.msgprint({
						title: "Inspection Booked",
						message: `
							<b>Order Number:</b> ${order_number}<br>
							<b>Order ID:</b> ${booking_id}<br>
							<b>Quality Inspections:</b> ${inspections.join(", ")}
						`,
						indicator: "green",
					});
				});
			},
			error: function () {
				frappe.dom.unfreeze();
			},
		});
	});
}

function _show_qr_booking_info(booked) {
	_show_rows_dialog(
		"MYQIMA Inspection Booked",
		_rows_table(booked, [
			["Row", "idx"],
			["Item", "item_code"],
			["Quality Inspection", "quality_inspection"],
			["Order Number", "order_number"],
			["Order ID", "booking_id"],
			["Product ID", "product_id"],
			["Status", "inspection_status"],
			["Overall Result", "overall_result"],
			["Decision", "report_decision"],
			["Decision Reason", "decision_reason"],
		])
	);
}

function _show_rows_dialog(title, table) {
	// msgprint is too narrow for several columns of long IDs, so use an extra-large dialog
	const d = new frappe.ui.Dialog({
		title: title,
		size: "extra-large",
		fields: [{ fieldtype: "HTML", fieldname: "rows", options: table }],
	});

	d.show();
}

function _fetch_qr_report(frm, unfetched) {
	const table = _rows_table(unfetched, REPORT_COLUMNS.slice(0, 4));

	frappe.confirm(`Fetch the MYQIMA report for these rows?<br><br>${table}`, () => {
		frappe.dom.freeze("Fetching MYQIMA report…");

		frappe.call({
			method: "qimaone_integrations.myqima.customizations.quality_request.quality_request.fetch_inspection_report",
			args: { quality_request_name: frm.doc.name },
			callback: function (r) {
				frappe.dom.unfreeze();
				if (r.exc) return;

				// An order not finished yet only gets its status saved, so its rows show no result
				frm.reload_doc().then(() => {
					_show_rows_dialog("MYQIMA Report", _rows_table(r.message, REPORT_COLUMNS));
				});
			},
			error: function () {
				frappe.dom.unfreeze();
			},
		});
	});
}

function _show_qr_cancel_dialog(frm) {
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
				method: "qimaone_integrations.myqima.customizations.quality_request.quality_request.cancel_inspection_booking",
				args: {
					quality_request_name: frm.doc.name,
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
