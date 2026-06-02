import frappe


def execute():
	from football_sni.tasks import update_game_department_factors, update_game_ranking_placeholder

	games = frappe.db.sql(
		"""
		select name, competition, start_time
		from `tabCompetition Game`
		where validated = 1
		order by start_time asc, name asc
		""",
		as_dict=True,
	)
	for game in games:
		update_game_department_factors(game)
		update_game_ranking_placeholder(game)
