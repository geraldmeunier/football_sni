# Copyright (c) 2026, Gerald Meunier and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class FNSIDepartment(Document):
	def autoname(self):
		if not self.competition or not self.team:
			frappe.throw(_("Competition and Team are required to name a department."))

		self.name = f"{self.competition} - {self.team}"
