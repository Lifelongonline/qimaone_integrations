app_name = "qimaone_integrations"
app_title = "Qimaone Integrations"
app_publisher = "gopal@8848digital.com"
app_description = "Push PO and products in Qimaone"
app_email = "gopal@8848digital.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

after_migrate = "qimaone_integrations.migrate.after_migrate"

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "qimaone_integrations",
# 		"logo": "/assets/qimaone_integrations/logo.png",
# 		"title": "Qimaone Integrations",
# 		"route": "/qimaone_integrations",
# 		"has_permission": "qimaone_integrations.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/qimaone_integrations/css/qimaone_integrations.css"
# app_include_js = "/assets/qimaone_integrations/js/qimaone_integrations.js"

# include js, css files in header of web template
# web_include_css = "/assets/qimaone_integrations/css/qimaone_integrations.css"
# web_include_js = "/assets/qimaone_integrations/js/qimaone_integrations.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "qimaone_integrations/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
doctype_js = {"Quality Inspection": "myqima/customizations/quality_inspection/quality_inspection.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "qimaone_integrations/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "qimaone_integrations.utils.jinja_methods",
# 	"filters": "qimaone_integrations.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "qimaone_integrations.install.before_install"
# after_install = "qimaone_integrations.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "qimaone_integrations.uninstall.before_uninstall"
# after_uninstall = "qimaone_integrations.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "qimaone_integrations.utils.before_app_install"
# after_app_install = "qimaone_integrations.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "qimaone_integrations.utils.before_app_uninstall"
# after_app_uninstall = "qimaone_integrations.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "qimaone_integrations.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"qimaone_integrations.tasks.all"
# 	],
# 	"daily": [
# 		"qimaone_integrations.tasks.daily"
# 	],
# 	"hourly": [
# 		"qimaone_integrations.tasks.hourly"
# 	],
# 	"weekly": [
# 		"qimaone_integrations.tasks.weekly"
# 	],
# 	"monthly": [
# 		"qimaone_integrations.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "qimaone_integrations.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "qimaone_integrations.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "qimaone_integrations.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["qimaone_integrations.utils.before_request"]
# after_request = ["qimaone_integrations.utils.after_request"]

# Job Events
# ----------
# before_job = ["qimaone_integrations.utils.before_job"]
# after_job = ["qimaone_integrations.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"qimaone_integrations.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }
