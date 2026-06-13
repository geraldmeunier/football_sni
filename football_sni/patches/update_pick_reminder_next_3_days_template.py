import frappe

from football_sni.tasks import PICK_REMINDER_EMAIL_HTML, PICK_REMINDER_TEMPLATE


def execute():
	if not frappe.db.exists("Email Template", PICK_REMINDER_TEMPLATE):
		return

	frappe.db.set_value(
		"Email Template",
		PICK_REMINDER_TEMPLATE,
		{
			"subject": "Tiny nudge: your next 3 days of picks are waiting",
			"use_html": 1,
			"response_html": PICK_REMINDER_EMAIL_HTML,
		},
	)
