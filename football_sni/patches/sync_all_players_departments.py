import frappe

from football_sni.football_sni.doctype.fnsi_department.fnsi_department import (
	sync_all_players_department,
)


def execute():
	for department in frappe.get_all(
		"FNSI Department",
		filters={"all_players": 1},
		pluck="name",
	):
		sync_all_players_department(department)
