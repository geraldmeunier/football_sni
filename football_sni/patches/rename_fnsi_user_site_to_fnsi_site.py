import frappe


def execute():
	if frappe.db.exists("DocType", "FNSI User Site") and not frappe.db.exists(
		"DocType", "FNSI Site"
	):
		frappe.rename_doc("DocType", "FNSI User Site", "FNSI Site", force=True)
