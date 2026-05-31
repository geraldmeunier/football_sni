# Copyright (c) 2026, Gerald Meunier and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class FNSIUserDepartment(Document):
	def autoname(self):
		self.name = f"{self.department} - {self.user}"
