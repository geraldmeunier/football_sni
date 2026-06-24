# Copyright (c) 2026, Gerald Meunier and contributors
# For license information, please see license.txt

from frappe.utils import cint
from frappe.model.document import Document

from football_sni.football_sni.doctype.fnsi_department.fnsi_department import (
	sync_user_all_players_memberships,
)


class CompetitionSubscription(Document):
	def on_update(self):
		previous = self.get_doc_before_save()
		if previous and (
			previous.competition != self.competition or previous.user != self.user
		):
			sync_user_all_players_memberships(
				previous.competition,
				previous.user,
				active=False,
			)

		sync_user_all_players_memberships(
			self.competition,
			self.user,
			active=not cint(self.stop_subscription),
		)

	def on_trash(self):
		sync_user_all_players_memberships(
			self.competition,
			self.user,
			active=False,
		)
