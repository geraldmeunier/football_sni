# Copyright (c) 2026, Gerald Meunier and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase


# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]


class IntegrationTestFNSIUserDepartment(IntegrationTestCase):
	def test_autoname_uses_department_and_user(self):
		doc = frappe.get_doc(
			{
				"doctype": "FNSI User Department",
				"department": "World Cup - Fouju",
				"user": "player@example.com",
				"status": "Asked",
			}
		)

		doc.autoname()

		self.assertEqual(doc.name, "World Cup - Fouju - player@example.com")

	def test_autoname_updates_when_membership_changes(self):
		doc = frappe.get_doc(
			{
				"doctype": "FNSI User Department",
				"department": "Euro - Paris",
				"user": "old@example.com",
				"status": "Asked",
			}
		)
		doc.autoname()

		doc.user = "new@example.com"
		doc.autoname()

		self.assertEqual(doc.name, "Euro - Paris - new@example.com")
