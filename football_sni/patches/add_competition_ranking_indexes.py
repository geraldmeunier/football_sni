import frappe


INDEXES = (
	(
		"Competition Department Ranking",
		("game", "department", "user"),
		"idx_cdr_game_department_user",
	),
	(
		"Competition Department Ranking",
		("competition", "department", "user", "game"),
		"idx_cdr_competition_department_user_game",
	),
	(
		"Competition Pick",
		("game", "user", "not_played"),
		"idx_cp_game_user_not_played",
	),
	(
		"Competition Pick",
		("competition", "user", "not_played", "game"),
		"idx_cp_competition_user_not_played_game",
	),
	(
		"Competition Game",
		("competition", "validated", "start_time"),
		"idx_cg_competition_validated_start_time",
	),
)


def execute():
	for doctype, fields, index_name in INDEXES:
		frappe.db.add_index(doctype, fields, index_name=index_name)
