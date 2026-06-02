import frappe


class CompetitionDepartmentRanking(frappe.model.document.Document):
	def autoname(self):
		if self.department and self.game and self.user:
			self.name = f"{self.department} - {self.game} - {self.user}"
