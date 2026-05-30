# Copyright (c) 2026, Gerald Meunier and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document


class CompetitionPick(Document):
	def validate(self):
		self.validate_integer_picks()

	def validate_integer_picks(self):
		for fieldname in ("pick_a", "pick_b"):
			value = self.get(fieldname)
			if value in (None, "", "null"):
				continue

			value = str(value).strip()
			if not re.fullmatch(r"-?\d+", value):
				label = self.meta.get_label(fieldname)
				frappe.throw(_("{0} must be an integer.").format(label))

			self.set(fieldname, str(int(value)))
