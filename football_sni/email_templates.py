import frappe


def get_or_create_email_template(template_name, subject, response_html):
	if frappe.db.exists("Email Template", template_name):
		return frappe.get_doc("Email Template", template_name)

	template = frappe.get_doc(
		{
			"doctype": "Email Template",
			"__newname": template_name,
			"subject": subject,
			"use_html": 1,
			"response_html": response_html,
		}
	)

	try:
		template.insert(ignore_permissions=True)
	except frappe.DuplicateEntryError:
		template = frappe.get_doc("Email Template", template_name)

	return template
