app_name = "posawesome"
app_title = "POS Awesome"
app_publisher = "WaleedAboHashima"
app_description = "POS Awesome — a modern point of sale for ERPNext"
app_email = "waleedsabry.abohashima@gmail.com"
app_license = "GPL-3.0"

# ------------------------------------------------------------------------------
# Desk assets
# ------------------------------------------------------------------------------
# The POS itself is a standalone SPA (see posawesome/www/posawesome.html); only the
# doctype form scripts below need to ride along with the desk bundle.

doctype_js = {
	"POS Profile": "posawesome/api/pos_profile.js",
	"Sales Invoice": "posawesome/api/invoice.js",
	"Company": "posawesome/api/company.js",
}

# ------------------------------------------------------------------------------
# Website
# ------------------------------------------------------------------------------
# Serve the SPA at /posawesome and let vue-router own everything beneath it.

website_route_rules = [
	{"from_route": "/posawesome/<path:app_path>", "to_route": "posawesome"},
]

# ------------------------------------------------------------------------------
# Installation
# ------------------------------------------------------------------------------

after_install = "posawesome.install.after_install"
after_migrate = "posawesome.install.after_migrate"
after_uninstall = "posawesome.uninstall.after_uninstall"

# ------------------------------------------------------------------------------
# Document events
# ------------------------------------------------------------------------------

doc_events = {
	"Sales Invoice": {
		"validate": "posawesome.posawesome.api.invoice.validate",
		"before_submit": "posawesome.posawesome.api.invoice.before_submit",
		"on_submit": "posawesome.posawesome.api.zimbabwe_fiscal.fiscalise_invoice",
		"before_cancel": "posawesome.posawesome.api.invoice.before_cancel",
	},
	"POS Closing Shift": {
		"on_submit": "posawesome.posawesome.api.zimbabwe_fiscal.close_day_for_pos_shift",
	},
	"Customer": {
		"validate": "posawesome.posawesome.api.customer.validate",
		"after_insert": "posawesome.posawesome.api.customer.after_insert",
	},
}

# Receipt helpers exposed to Jinja print formats.

jinja = {
	"methods": [
		"posawesome.posawesome.api.zimbabwe_fiscal.get_qr_data_uri",
	],
}

# ------------------------------------------------------------------------------
# Scheduled tasks
# ------------------------------------------------------------------------------

scheduler_events = {
	"hourly_long": [
		"posawesome.posawesome.api.offline.prune_expired_sync_log",
	],
}

# ------------------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------------------

fixtures = [
	{
		"doctype": "Custom Field",
		"filters": [["name", "like", "%-posa_%"]],
	},
	{
		"doctype": "Custom Field",
		"filters": [
			[
				"name",
				"in",
				(
					"POS Profile-use_customer_credit",
					"POS Profile-use_cashback",
					"POS Profile-hide_expected_amount",
					"POS Profile-custom_allow_select_sales_order",
					"POS Profile-column_break_dqsba",
					"POS Profile-column_break_anyol",
					"POS Profile-column_break_uolvm",
					"POS Profile-pose_use_limit_search",
					"POS Profile-pos_awesome_payments",
				),
			]
		],
	},
	{
		"doctype": "Property Setter",
		"filters": [["name", "in", ("Sales Invoice-posa_pos_opening_shift-no_copy",)]],
	},
]
