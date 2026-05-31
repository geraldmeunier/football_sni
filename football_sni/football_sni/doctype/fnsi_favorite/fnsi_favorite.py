# Copyright (c) 2026, Gerald Meunier and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class FNSIFavorite(Document):
	def autoname(self):
		self.name = f"{self.competition} - {self.user}"
