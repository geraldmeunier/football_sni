import frappe


class CompetitionCategoryRanking(frappe.model.document.Document):
	def autoname(self):
		if self.category_type and self.category and self.game:
			self.name = f"{self.category_type} - {self.category} - {self.game}"
