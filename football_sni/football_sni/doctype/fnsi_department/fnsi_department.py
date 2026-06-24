# Copyright (c) 2026, Gerald Meunier and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class FNSIDepartment(Document):
	def validate(self):
		self.start_from = cint(self.start_from) or 1
		self.end_by = cint(self.end_by) or 1000
		if self.start_from < 1 or self.end_by < 1:
			frappe.throw(_("Start From and End By must be positive game IDs."))
		if self.start_from > self.end_by:
			frappe.throw(_("Start From cannot be greater than End By."))

	def autoname(self):
		if not self.competition or not self.team:
			frappe.throw(_("Competition and Team are required to name a department."))

		self.name = f"{self.competition} - {self.team}"

	def on_update(self):
		if cint(self.all_players):
			sync_all_players_department(self.name)


def sync_all_players_department(department):
	department_doc = frappe.db.get_value(
		"FNSI Department",
		department,
		["name", "competition", "all_players"],
		as_dict=True,
	)
	if not department_doc or not cint(department_doc.all_players):
		return

	active_users = set(frappe.db.sql_list(
		"""
		select distinct subscription.user
		from `tabCompetition Subscription` subscription
		where subscription.competition = %(competition)s
			and coalesce(subscription.stop_subscription, 0) = 0
			and coalesce(subscription.user, '') != ''
		""",
		{"competition": department_doc.competition},
	))
	memberships = frappe.get_all(
		"FNSI User Department",
		filters={"department": department_doc.name},
		fields=["name", "user", "status"],
	)
	existing_users = {membership.user for membership in memberships}

	for membership in memberships:
		if membership.user not in active_users:
			frappe.delete_doc("FNSI User Department", membership.name, ignore_permissions=True)
		elif membership.status != "Validated":
			frappe.db.set_value(
				"FNSI User Department",
				membership.name,
				"status",
				"Validated",
				update_modified=False,
			)

	for user in sorted(active_users - existing_users):
		frappe.get_doc(
			{
				"doctype": "FNSI User Department",
				"department": department_doc.name,
				"user": user,
				"status": "Validated",
			}
		).insert(ignore_permissions=True)


def sync_user_all_players_memberships(competition, user, active=True):
	if not competition or not user:
		return

	departments = frappe.get_all(
		"FNSI Department",
		filters={"competition": competition, "all_players": 1},
		pluck="name",
	)
	for department in departments:
		membership = frappe.db.exists(
			"FNSI User Department",
			{"department": department, "user": user},
		)
		if active:
			if membership:
				frappe.db.set_value(
					"FNSI User Department",
					membership,
					"status",
					"Validated",
					update_modified=False,
				)
			else:
				frappe.get_doc(
					{
						"doctype": "FNSI User Department",
						"department": department,
						"user": user,
						"status": "Validated",
					}
				).insert(ignore_permissions=True)
		elif membership:
			frappe.delete_doc("FNSI User Department", membership, ignore_permissions=True)
