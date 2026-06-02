import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	if frappe.db.exists("Custom Field", "User-fsni_rgpd_consent"):
		return

	create_custom_fields(
		{
			"User": [
				{
					"fieldname": "fsni_rgpd_consent",
					"fieldtype": "Check",
					"label": "Football SNI RGPD Consent",
					"insert_after": "location",
					"default": "0",
					"no_copy": 1,
				},
			]
		},
		update=True,
	)
