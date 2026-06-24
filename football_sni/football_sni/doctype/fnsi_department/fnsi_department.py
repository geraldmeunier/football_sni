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
