# Copyright (c) 2026, Gerald Meunier and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from football_sni.templates.pages.game_result import is_department_ranking_game

# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]



class IntegrationTestCompetitionRanking(IntegrationTestCase):
	"""
	Integration tests for CompetitionRanking.
	Use this class for testing interactions between multiple components.
	"""

	def test_department_ranking_game_range_is_inclusive(self):
		department = frappe._dict(start_from=25, end_by=50)

		self.assertTrue(is_department_ranking_game(department, frappe._dict(game_id=25)))
		self.assertTrue(is_department_ranking_game(department, frappe._dict(game_id=50)))

	def test_department_ranking_game_range_excludes_games_outside_bounds(self):
		department = frappe._dict(start_from=25, end_by=50)

		self.assertFalse(is_department_ranking_game(department, frappe._dict(game_id=24)))
		self.assertFalse(is_department_ranking_game(department, frappe._dict(game_id=51)))
