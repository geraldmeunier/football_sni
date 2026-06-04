import frappe

from football_sni.tasks import (
	AVAILABLE_PICKS_EMAIL_HTML,
	AVAILABLE_PICKS_TEMPLATE,
	PICK_REMINDER_EMAIL_HTML,
	PICK_REMINDER_TEMPLATE,
)


def execute():
	update_template(
		AVAILABLE_PICKS_TEMPLATE,
		"Your picks are ready - time to make the call!",
		AVAILABLE_PICKS_EMAIL_HTML,
	)
	update_template(
		PICK_REMINDER_TEMPLATE,
		"Tiny nudge: your picks are still waiting",
		PICK_REMINDER_EMAIL_HTML,
	)


def update_template(template_name, subject, response_html):
	if not frappe.db.exists("Email Template", template_name):
		return

	current_html = frappe.db.get_value("Email Template", template_name, "response_html") or ""
	if "image_url" not in current_html:
		return

	frappe.db.set_value(
		"Email Template",
		template_name,
		{
			"subject": subject,
			"use_html": 1,
			"response_html": response_html,
		},
	)
