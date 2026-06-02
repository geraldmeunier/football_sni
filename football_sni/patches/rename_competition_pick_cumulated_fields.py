import frappe


TEMP_SITE_CUMULATED_FIELD = "_tmp_total_points_site_cumulated"


def execute():
	doctype = "Competition Pick"
	if not frappe.db.table_exists(doctype):
		return

	if frappe.db.has_column(doctype, "total_points_cumulated") and not frappe.db.has_column(
		doctype, TEMP_SITE_CUMULATED_FIELD
	):
		frappe.db.rename_column(doctype, "total_points_cumulated", TEMP_SITE_CUMULATED_FIELD)

	if frappe.db.has_column(doctype, "total_pöints_cumulated") and not frappe.db.has_column(
		doctype, "total_points_cumulated"
	):
		frappe.db.rename_column(doctype, "total_pöints_cumulated", "total_points_cumulated")

	if frappe.db.has_column(doctype, TEMP_SITE_CUMULATED_FIELD) and not frappe.db.has_column(
		doctype, "total_points_site_cumulated"
	):
		frappe.db.rename_column(doctype, TEMP_SITE_CUMULATED_FIELD, "total_points_site_cumulated")
