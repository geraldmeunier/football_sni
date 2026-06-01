app_name = "football_sni"
app_title = "Football SNI"
app_publisher = "Gerald Meunier"
app_description = "Perform Bets with Colleagues"
app_email = "gerald.meunier@daliak.net"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "football_sni",
# 		"logo": "/assets/football_sni/logo.png",
# 		"title": "Football SNI",
# 		"route": "/football_sni",
# 		"has_permission": "football_sni.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/football_sni/css/football_sni.css"
# app_include_js = "/assets/football_sni/js/football_sni.js"

# include js, css files in header of web template
web_include_css = "/assets/football_sni/css/football_sni.css"
web_include_js = "/assets/football_sni/js/football_sni.js"

before_login = "football_sni.security.validate_turnstile_for_login"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "football_sni/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "football_sni/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page
get_website_user_home_page = "football_sni.website.get_website_user_home_page"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "football_sni.utils.jinja_methods",
# 	"filters": "football_sni.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "football_sni.install.before_install"
# after_install = "football_sni.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "football_sni.uninstall.before_uninstall"
# after_uninstall = "football_sni.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "football_sni.utils.before_app_install"
# after_app_install = "football_sni.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "football_sni.utils.before_app_uninstall"
# after_app_uninstall = "football_sni.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "football_sni.notifications.get_notification_config"

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

scheduler_events = {
	"all": [
		"football_sni.tasks.all"
	],
	"cron": {
		"0 12 * * *": [
			"football_sni.tasks.send_daily_pick_reminders"
		]
	},
# 	"daily": [
# 		"football_sni.tasks.daily"
# 	],
	"hourly": [
		"football_sni.tasks.close_competition_games_before_start"
	],
# 	"weekly": [
# 		"football_sni.tasks.weekly"
# 	],
# 	"monthly": [
# 		"football_sni.tasks.monthly"
# 	],
}

# Testing
# -------

# before_tests = "football_sni.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "football_sni.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
override_whitelisted_methods = {
	"frappe.core.doctype.user.user.sign_up": "football_sni.signup.sign_up"
}
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "football_sni.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["football_sni.utils.before_request"]
# after_request = ["football_sni.utils.after_request"]

# Job Events
# ----------
# before_job = ["football_sni.utils.before_job"]
# after_job = ["football_sni.utils.after_job"]

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
# 	"football_sni.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

