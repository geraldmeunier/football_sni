# Copyright (c) 2026, Gerald Meunier and contributors
# For license information, please see license.txt

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import frappe
from football_sni.email_templates import get_or_create_email_template
from frappe.utils import (
	add_to_date,
	cint,
	convert_utc_to_timezone,
	flt,
	format_datetime,
	get_datetime,
	get_system_timezone,
	get_url,
	now_datetime,
)

AVAILABLE_PICKS_TEMPLATE = "Available Picks"
PICK_REMINDER_TEMPLATE = "Pick Reminder"
PICK_REMINDER_UPCOMING_DAYS = 3
CATEGORY_DEPARTMENT = "Department"
CATEGORY_COUNTRY = "Country"
CATEGORY_SITE = "Site"


def get_department_game_range_condition(department_alias="department", game_alias="game"):
	return f"""
		cast({game_alias}.game_id as unsigned) between
			coalesce(nullif({department_alias}.start_from, 0), 1)
			and coalesce(nullif({department_alias}.end_by, 0), 1000)
	"""


def all():
	create_new_subscription_picks()


def close_competition_games_before_start():
	cutoff = add_to_date(now_datetime(), hours=1)
	games = frappe.get_all(
		"Competition Game",
		filters={"open": 1, "start_time": ("<=", cutoff)},
		pluck="name",
	)

	for game in games:
		frappe.db.set_value("Competition Game", game, {"open": 0, "do_not_show": 0})
		frappe.db.sql(
			"""
			update `tabCompetition Pick`
			set not_played = 1
			where game = %(game)s
				and (
					pick_a is null
					or pick_a = ''
					or pick_a = 'null'
					or pick_b is null
					or pick_b = ''
					or pick_b = 'null'
				)
			""",
			{"game": game},
		)
		frappe.db.set_value("Competition Pick", {"game": game}, "open", 0)

	return len(games)


def validate_score_updated_competition_games():
	games = get_unvalidated_score_updated_competition_games()
	if not games:
		return {"validated": 0, "pending_scores": 0}

	pending_games = [game for game in games if is_score_pending(game)]
	if pending_games:
		return {"validated": 0, "pending_scores": len(pending_games)}

	validated = 0
	for game in games:
		validate_competition_game(game)
		validated += 1

	return {"validated": validated, "pending_scores": 0}


def validate_yesterday_competition_games(is_retry=False):
	return validate_score_updated_competition_games()


def get_unvalidated_score_updated_competition_games():
	return frappe.db.sql(
		"""
		select
			cg.name,
			cg.competition,
			cg.round,
			cg.start_time,
			cg.score_a,
			cg.score_b,
			cg.score_updated,
			c.time_zone
		from `tabCompetition Game` cg
		inner join `tabCompetition` c on c.name = cg.competition
		where cg.validated = 0
			and cg.score_updated = 1
		order by cg.start_time, cg.name
		""",
		as_dict=True,
	)


def get_competition_time_zone(time_zone=None):
	time_zone = time_zone or get_system_timezone() or "Europe/Paris"
	try:
		ZoneInfo(time_zone)
	except ZoneInfoNotFoundError:
		return "Europe/Paris"
	return time_zone


def is_score_pending(game):
	return not cint(game.score_updated) or parse_score(game.score_a) is None or parse_score(game.score_b) is None


def validate_competition_game(game):
	result = recalculate_competition_game(game)
	if result["skipped"]:
		return result

	frappe.db.set_value(
		"Competition Game",
		game.name,
		{"validated": 1},
		update_modified=False,
	)
	return result


def recalculate_competition_game(game):
	score_a = parse_score(game.score_a)
	score_b = parse_score(game.score_b)
	if score_a is None or score_b is None:
		return {"picks": 0, "rankings": 0, "skipped": 1}

	coefficient = get_round_coefficient(game.competition, game.round)

	picks = frappe.get_all(
		"Competition Pick",
		filters={"game": game.name},
		fields=["name", "pick_a", "pick_b"],
	)
	for pick in picks:
		result = calculate_pick_result(pick.pick_a, pick.pick_b, score_a, score_b)
		frappe.db.set_value(
			"Competition Pick",
			pick.name,
			{
				"points": result["points"],
				"coefficient": coefficient,
				"exact_result": result["exact_result"],
				"good_difference": result["good_difference"],
				"good_trend": result["good_trend"],
				"no_play": result["did_play"],
				"not_played": 0 if result["did_play"] else 1,
			},
			update_modified=False,
		)

	update_game_factors(game.name)
	update_game_site_factors(game)
	update_game_department_factors(game)
	ranking_result = update_game_ranking_placeholder(game)

	return {"picks": len(picks), "rankings": ranking_result["rankings"], "skipped": 0}


def get_round_coefficient(competition, round_name):
	coefficient = frappe.db.get_value(
		"Competition Round List",
		{"parent": competition, "round": round_name},
		"coefficient",
	)
	return flt(coefficient) if coefficient is not None else 1


def calculate_pick_result(pick_a, pick_b, score_a, score_b):
	pick_a = parse_score(pick_a)
	pick_b = parse_score(pick_b)
	if pick_a is None or pick_b is None:
		return get_empty_pick_result(did_play=0)

	result = get_empty_pick_result(did_play=1)
	pick_difference = pick_a - pick_b
	score_difference = score_a - score_b

	if pick_a == score_a and pick_b == score_b:
		result["points"] = 4
		result["exact_result"] = 1
	elif score_a != score_b and pick_difference == score_difference:
		result["points"] = 2
		result["good_difference"] = 1
	elif score_a != score_b and sign(pick_difference) == sign(score_difference):
		result["points"] = 1
		result["good_trend"] = 1
	elif score_a == score_b and pick_a == pick_b:
		result["points"] = 1
		result["good_trend"] = 1

	return result


def get_empty_pick_result(did_play):
	return {
		"points": 0,
		"exact_result": 0,
		"good_difference": 0,
		"good_trend": 0,
		"did_play": did_play,
	}


def parse_score(value):
	if value is None or value == "":
		return None
	if isinstance(value, str) and value.strip().lower() in {"", "null", "none"}:
		return None
	try:
		return cint(value)
	except Exception:
		return None


def sign(value):
	if value > 0:
		return 1
	if value < 0:
		return -1
	return 0


def update_game_factors(game):
	aggregate = get_pick_factor_aggregate("cp.game = %(game)s", {"game": game})
	frappe.db.sql(
		"""
		update `tabCompetition Pick`
		set factor = %(factor)s,
			total_points = coalesce(cast(points as decimal(18,6)), 0)
				* coalesce(cast(coefficient as decimal(18,6)), 0)
				* %(factor)s
		where game = %(game)s
		""",
		{"game": game, "factor": aggregate["factor"]},
	)


def update_game_site_factors(game):
	frappe.db.sql(
		"""
		update `tabCompetition Pick`
		set factor_site = 0,
			total_points_site = 0
		where game = %(game)s
		""",
		{"game": game.name},
	)

	for site in frappe.get_all("FNSI Site", pluck="name"):
		aggregate = get_pick_factor_aggregate(
			"cp.game = %(game)s and user.location = %(site)s",
			{"game": game.name, "site": site},
			join_user=True,
		)
		frappe.db.sql(
			"""
			update `tabCompetition Pick` cp
			inner join `tabUser` user on user.name = cp.user
			set cp.factor_site = %(factor)s,
				cp.total_points_site = coalesce(cast(cp.points as decimal(18,6)), 0)
					* coalesce(cast(cp.coefficient as decimal(18,6)), 0)
					* %(factor)s
			where cp.game = %(game)s
				and user.location = %(site)s
			""",
			{"game": game.name, "site": site, "factor": aggregate["factor"]},
		)


def update_game_department_factors(game):
	frappe.db.sql(
		"""
		update `tabCompetition Pick`
		set factor_department = 0,
			total_points_department = 0
		where game = %(game)s
		""",
		{"game": game.name},
	)
	frappe.db.delete("Competition Department Ranking", {"game": game.name})

	departments = frappe.db.sql_list(
		f"""
		select department.name
		from `tabFNSI Department` department
		inner join `tabCompetition Game` game on game.name = %(game)s
		where department.competition = %(competition)s
			and {get_department_game_range_condition()}
		order by department.name
		""",
		{"competition": game.competition, "game": game.name},
	)
	for department in departments:
		department_filter = """
			cp.game = %(game)s
			and exists (
				select 1
				from `tabFNSI User Department` fud
				where fud.user = cp.user
					and fud.department = %(department)s
					and fud.status = 'Validated'
			)
		"""
		aggregate = get_pick_factor_aggregate(
			department_filter,
			{"game": game.name, "department": department},
		)
		frappe.db.sql(
			"""
			update `tabCompetition Pick` cp
			set cp.factor_department = %(factor)s,
				cp.total_points_department = coalesce(cast(cp.points as decimal(18,6)), 0)
					* coalesce(cast(cp.coefficient as decimal(18,6)), 0)
					* %(factor)s
			where cp.game = %(game)s
				and exists (
					select 1
					from `tabFNSI User Department` fud
					where fud.user = cp.user
						and fud.department = %(department)s
						and fud.status = 'Validated'
				)
			""",
			{"game": game.name, "department": department, "factor": aggregate["factor"]},
		)
		users = frappe.db.sql(
			"""
			select cp.user, cp.points, cp.coefficient
			from `tabCompetition Pick` cp
			where cp.game = %(game)s
				and exists (
					select 1
					from `tabFNSI User Department` fud
					where fud.user = cp.user
						and fud.department = %(department)s
						and fud.status = 'Validated'
				)
			""",
			{"game": game.name, "department": department},
			as_dict=True,
		)
		for row in users:
			frappe.get_doc(
				{
					"doctype": "Competition Department Ranking",
					"competition": game.competition,
					"game": game.name,
					"department": department,
					"user": row.user,
					"factor": aggregate["factor"],
					"total_points": flt(row.points) * flt(row.coefficient) * aggregate["factor"],
				}
			).insert(ignore_permissions=True)


def get_pick_factor_aggregate(where_clause, params, join_user=False):
	user_join = "inner join `tabUser` user on user.name = cp.user" if join_user else ""
	row = frappe.db.sql(
		f"""
		select
			coalesce(sum(cp.exact_result), 0) as exact_results,
			coalesce(sum(cp.good_difference), 0) as good_differences,
			coalesce(sum(cp.good_trend), 0) as good_trends,
			coalesce(sum(cp.no_play), 0) as did_play
		from `tabCompetition Pick` cp
		{user_join}
		where {where_clause}
		""",
		params,
		as_dict=True,
	)[0]

	number_good_trends = cint(row.exact_results) + cint(row.good_differences) + cint(row.good_trends)
	number_players = cint(row.did_play)
	return {
		"factor": get_factor(number_good_trends, number_players),
		"total_points": number_good_trends,
	}


def get_factor(number_good_trends, number_players):
	if number_players != 1:
		factor = 1 + round(1 - ((number_good_trends - 1) / (number_players - 1)), 3)
	else:
		factor = 0
	if number_good_trends == 0:
		factor = 0
	return factor


def update_game_category_rankings(game):
	game = get_ranking_game(game)
	if not game:
		return {"rankings": 0}

	frappe.db.delete("Competition Category Ranking", {"game": game.name})
	created = 0
	for row in get_game_category_point_rows(game):
		frappe.get_doc(
			{
				"doctype": "Competition Category Ranking",
				"competition": game.competition,
				"game": game.name,
				"category_type": row.category_type,
				"category": row.category,
				"category_label": row.category_label,
				"users_count": row.users_count,
				"total_points": row.total_points,
				"total_points_cumulated": 0,
			}
		).insert(ignore_permissions=True)
		created += 1

	update_game_category_cumulated_points(game)
	prior_rankings = get_prior_category_rankings(game)
	ranking_maps = get_category_rankings(game)
	update_category_ranking_rows(game, ranking_maps, prior_rankings)
	return {"rankings": created}


def get_game_category_point_rows(game):
	rows = []
	rows.extend(get_game_department_category_point_rows(game))
	rows.extend(get_game_country_category_point_rows(game))
	rows.extend(get_game_site_category_point_rows(game))
	return rows


def get_game_department_category_point_rows(game):
	return frappe.db.sql(
		f"""
		select
			%(category_type)s as category_type,
			user_department.department as category,
			coalesce(nullif(department.team, ''), department.name) as category_label,
			count(*) as users_count,
			coalesce(sum(coalesce(cast(pick.total_points as decimal(18,6)), 0)), 0) / count(*) as total_points
		from `tabCompetition Pick` pick
		inner join `tabFNSI User Department` user_department
			on user_department.user = pick.user
			and user_department.status = 'Validated'
		inner join `tabFNSI Department` department
			on department.name = user_department.department
			and department.competition = pick.competition
		inner join `tabCompetition Game` game on game.name = pick.game
		where pick.game = %(game)s
			and pick.competition = %(competition)s
			and pick.not_played = 0
			and {get_department_game_range_condition()}
		group by user_department.department, department.team, department.name
		order by category_label asc, user_department.department asc
		""",
		{
			"category_type": CATEGORY_DEPARTMENT,
			"competition": game.competition,
			"game": game.name,
		},
		as_dict=True,
	)


def get_game_country_category_point_rows(game):
	return frappe.db.sql(
		"""
		select
			%(category_type)s as category_type,
			site.country as category,
			site.country as category_label,
			count(*) as users_count,
			coalesce(sum(coalesce(cast(pick.total_points as decimal(18,6)), 0)), 0) / count(*) as total_points
		from `tabCompetition Pick` pick
		inner join `tabUser` user on user.name = pick.user
		inner join `tabFNSI Site` site on site.name = user.location
		where pick.game = %(game)s
			and pick.competition = %(competition)s
			and pick.not_played = 0
			and coalesce(site.country, '') != ''
		group by site.country
		order by site.country asc
		""",
		{
			"category_type": CATEGORY_COUNTRY,
			"competition": game.competition,
			"game": game.name,
		},
		as_dict=True,
	)


def get_game_site_category_point_rows(game):
	return frappe.db.sql(
		"""
		select
			%(category_type)s as category_type,
			site.name as category,
			coalesce(nullif(site.site, ''), site.name) as category_label,
			count(*) as users_count,
			coalesce(sum(coalesce(cast(pick.total_points as decimal(18,6)), 0)), 0) / count(*) as total_points
		from `tabCompetition Pick` pick
		inner join `tabUser` user on user.name = pick.user
		inner join `tabFNSI Site` site on site.name = user.location
		where pick.game = %(game)s
			and pick.competition = %(competition)s
			and pick.not_played = 0
		group by site.name, site.site
		order by category_label asc, site.name asc
		""",
		{
			"category_type": CATEGORY_SITE,
			"competition": game.competition,
			"game": game.name,
		},
		as_dict=True,
	)


def update_game_ranking_placeholder(game):
	game = get_ranking_game(game)
	if not game:
		return {"rankings": 0}

	update_game_cumulated_points(game)
	update_game_category_rankings(game)
	prior_rankings = get_prior_rankings(game)
	ranking_maps = get_game_ranking_maps(game)
	department_prior_rankings = get_prior_department_rankings(game)
	department_ranking_maps = get_department_rankings(game)
	update_department_ranking_rows(game, department_ranking_maps, department_prior_rankings)
	legacy_department_rankings = get_legacy_department_ranking_map(department_ranking_maps)

	frappe.db.delete("Competition Ranking", {"game": game.name})
	created = 0
	for pick in get_game_ranking_picks(game.name):
		frappe.get_doc(
			{
				"doctype": "Competition Ranking",
				"competition": game.competition,
				"game": game.name,
				"user": pick.user,
				"date": get_datetime(game.start_time).date() if game.start_time else None,
				"prior_ranking": prior_rankings["ranking"].get(pick.user, 0),
				"prior_ranking_site": prior_rankings["ranking_site"].get(pick.user, 0),
				"prior_ranking_department": prior_rankings["ranking_department"].get(pick.user, 0),
				"ranking": ranking_maps["ranking"].get(pick.user, 0),
				"ranking_site": ranking_maps["ranking_site"].get(pick.user, 0),
				"ranking_department": legacy_department_rankings.get(pick.user, 0),
			}
		).insert(ignore_permissions=True)
		created += 1

	clear_rankings_cache()
	return {"rankings": created}


def clear_rankings_cache():
	from football_sni.templates.pages.rankings import clear_rankings_cache as clear_cache

	clear_cache()


def get_ranking_game(game):
	game_name = game.name if hasattr(game, "name") else game
	if not game_name:
		return None

	game_doc = frappe.db.get_value(
		"Competition Game",
		game_name,
		["name", "competition", "start_time"],
		as_dict=True,
	)
	return game_doc


def update_game_cumulated_points(game):
	update_game_cumulated_points_for_scope(
		game,
		"`total_points_cumulated`",
		"factor",
	)
	update_game_cumulated_points_for_scope(
		game,
		"total_points_site_cumulated",
		"factor_site",
	)
	update_game_cumulated_points_for_scope(
		game,
		"total_points_department_cumulated",
		"factor_department",
	)
	update_game_department_cumulated_points(game)


def update_game_category_cumulated_points(game):
	frappe.db.sql(
		"""
		update `tabCompetition Category Ranking` current_ranking
		set current_ranking.total_points_cumulated = (
			select coalesce(sum(coalesce(cast(category_ranking.total_points as decimal(18,6)), 0)), 0)
			from `tabCompetition Category Ranking` category_ranking
			inner join `tabCompetition Game` ranking_game on ranking_game.name = category_ranking.game
			where category_ranking.competition = %(competition)s
				and category_ranking.category_type = current_ranking.category_type
				and category_ranking.category = current_ranking.category
				and (
					category_ranking.game = %(game)s
					or (
						ranking_game.validated = 1
						and (
							ranking_game.start_time < %(start_time)s
							or %(start_time)s is null
						)
					)
				)
		)
		where current_ranking.game = %(game)s
		""",
		{
			"competition": game.competition,
			"game": game.name,
			"start_time": game.start_time,
		},
	)


def update_game_cumulated_points_for_scope(game, cumulative_field, factor_field):
	frappe.db.sql(
		f"""
		update `tabCompetition Pick` current_pick
		set current_pick.{cumulative_field} = (
			select coalesce(sum(
				coalesce(cast(pick.points as decimal(18,6)), 0)
				* coalesce(cast(pick.coefficient as decimal(18,6)), 0)
				* coalesce(cast(pick.{factor_field} as decimal(18,6)), 0)
			), 0)
			from `tabCompetition Pick` pick
			inner join `tabCompetition Game` pick_game on pick_game.name = pick.game
			where pick.competition = %(competition)s
				and pick.user = current_pick.user
				and pick.not_played = 0
				and (
					pick.game = %(game)s
					or (
						pick_game.validated = 1
						and (
							pick_game.start_time < %(start_time)s
							or %(start_time)s is null
						)
					)
				)
		)
		where current_pick.game = %(game)s
		""",
		{
			"competition": game.competition,
			"game": game.name,
			"start_time": game.start_time,
		},
	)


def update_game_department_cumulated_points(game):
	frappe.db.sql(
		f"""
		update `tabCompetition Department Ranking` current_ranking
		inner join `tabFNSI Department` current_department
			on current_department.name = current_ranking.department
		inner join `tabCompetition Game` current_game
			on current_game.name = current_ranking.game
		set current_ranking.total_points_cumulated = (
			select coalesce(sum(
				coalesce(cast(pick.points as decimal(18,6)), 0)
				* coalesce(cast(pick.coefficient as decimal(18,6)), 0)
				* coalesce(cast(department_ranking.factor as decimal(18,6)), 0)
			), 0)
			from `tabCompetition Department Ranking` department_ranking
			inner join `tabCompetition Pick` pick
				on pick.game = department_ranking.game
				and pick.user = department_ranking.user
			inner join `tabCompetition Game` pick_game on pick_game.name = pick.game
			inner join `tabFNSI Department` department
				on department.name = department_ranking.department
			where department_ranking.competition = %(competition)s
				and department_ranking.department = current_ranking.department
				and department_ranking.user = current_ranking.user
				and pick.not_played = 0
				and {get_department_game_range_condition('department', 'pick_game')}
				and (
					pick.game = %(game)s
					or (
						pick_game.validated = 1
						and (
							pick_game.start_time < %(start_time)s
							or %(start_time)s is null
						)
					)
				)
		)
		where current_ranking.game = %(game)s
			and {get_department_game_range_condition('current_department', 'current_game')}
		""",
		{
			"competition": game.competition,
			"game": game.name,
			"start_time": game.start_time,
		},
	)


def get_prior_rankings(game):
	prior_rankings = {
		"ranking": {},
		"ranking_site": {},
		"ranking_department": {},
	}
	previous_game = get_previous_ranking_game(game)
	if not previous_game:
		return prior_rankings

	rows = frappe.get_all(
		"Competition Ranking",
		filters={"competition": game.competition, "game": previous_game},
		fields=["user", "ranking", "ranking_site", "ranking_department"],
	)
	for row in rows:
		prior_rankings["ranking"][row.user] = cint(row.ranking)
		prior_rankings["ranking_site"][row.user] = cint(row.ranking_site)
		prior_rankings["ranking_department"][row.user] = cint(row.ranking_department)

	return prior_rankings


def get_prior_department_rankings(game):
	if not game.start_time:
		return {}

	rows = frappe.db.sql(
		f"""
		select ranking.department, ranking.user, ranking.ranking
		from `tabCompetition Department Ranking` ranking
		inner join `tabCompetition Game` ranking_game on ranking_game.name = ranking.game
		inner join `tabFNSI Department` department on department.name = ranking.department
		where ranking.competition = %(competition)s
			and ranking.ranking > 0
			and {get_department_game_range_condition('department', 'ranking_game')}
			and ranking.game = (
				select prior_ranking.game
				from `tabCompetition Department Ranking` prior_ranking
				inner join `tabCompetition Game` prior_game on prior_game.name = prior_ranking.game
				where prior_ranking.competition = ranking.competition
					and prior_ranking.department = ranking.department
					and prior_game.validated = 1
					and prior_game.start_time < %(start_time)s
					and {get_department_game_range_condition('department', 'prior_game')}
				order by prior_game.start_time desc, prior_game.name desc
				limit 1
			)
		""",
		{"competition": game.competition, "start_time": game.start_time},
		as_dict=True,
	)
	return {(row.department, row.user): cint(row.ranking) for row in rows}


def get_prior_category_rankings(game):
	previous_game = get_previous_ranking_game(game)
	if not previous_game:
		return {}

	rows = frappe.get_all(
		"Competition Category Ranking",
		filters={"competition": game.competition, "game": previous_game},
		fields=["category_type", "category", "ranking"],
	)
	return {(row.category_type, row.category): cint(row.ranking) for row in rows}


def get_previous_ranking_game(game):
	if not game.start_time:
		return None

	rows = frappe.db.sql(
		"""
		select game.name
		from `tabCompetition Game` game
		where game.competition = %(competition)s
			and game.validated = 1
			and game.start_time < %(start_time)s
			and exists (
				select 1
				from `tabCompetition Ranking` ranking
				where ranking.game = game.name
			)
		order by game.start_time desc, game.name desc
		limit 1
		""",
		{"competition": game.competition, "start_time": game.start_time},
		as_dict=True,
	)
	return rows[0].name if rows else None


def get_game_ranking_picks(game):
	return frappe.db.sql(
		"""
		select pick.user
		from `tabCompetition Pick` pick
		inner join `tabUser` user on user.name = pick.user
		where pick.game = %(game)s
		order by coalesce(nullif(user.full_name, ''), user.name), pick.user
		""",
		{"game": game},
		as_dict=True,
	)


def get_game_ranking_maps(game):
	return {
		"ranking": get_rankings_by_query(
			"""
			select
				pick.user,
				coalesce(cast(pick.`total_points_cumulated` as decimal(18,6)), 0) as score,
				coalesce(nullif(user.full_name, ''), user.name) as user_full_name
			from `tabCompetition Pick` pick
			inner join `tabUser` user on user.name = pick.user
			where pick.game = %(game)s
			""",
			{"game": game.name},
		),
		"ranking_site": get_site_rankings(game),
		"ranking_department": {},
	}


def get_site_rankings(game):
	rankings = {}
	sites = frappe.db.sql_list(
		"""
		select distinct user.location
		from `tabCompetition Pick` pick
		inner join `tabUser` user on user.name = pick.user
		where pick.game = %(game)s
			and coalesce(user.location, '') != ''
		order by user.location
		""",
		{"game": game.name},
	)
	for site in sites:
		rankings.update(
			get_rankings_by_query(
				"""
				select
					pick.user,
					coalesce(cast(pick.total_points_site_cumulated as decimal(18,6)), 0) as score,
					coalesce(nullif(user.full_name, ''), user.name) as user_full_name
				from `tabCompetition Pick` pick
				inner join `tabUser` user on user.name = pick.user
				where pick.game = %(game)s
					and user.location = %(site)s
				""",
				{"game": game.name, "site": site},
			)
		)
	return rankings


def get_department_rankings(game):
	rankings = {}
	departments = frappe.db.sql_list(
		f"""
		select department.name
		from `tabFNSI Department` department
		inner join `tabCompetition Game` ranking_game on ranking_game.name = %(game)s
		where department.competition = %(competition)s
			and {get_department_game_range_condition('department', 'ranking_game')}
		order by department.name
		""",
		{"competition": game.competition, "game": game.name},
	)
	for department in departments:
		for user, ranking in get_rankings_by_query(
			"""
			select
				department_ranking.user,
				coalesce(cast(department_ranking.total_points_cumulated as decimal(18,6)), 0) as score,
				coalesce(nullif(user.full_name, ''), user.name) as user_full_name
			from `tabCompetition Department Ranking` department_ranking
			inner join `tabUser` user on user.name = department_ranking.user
			where department_ranking.game = %(game)s
				and department_ranking.department = %(department)s
			""",
			{"game": game.name, "department": department},
		).items():
			rankings[(department, user)] = ranking
	return rankings


def get_category_rankings(game):
	rankings = {}
	for category_type in (CATEGORY_DEPARTMENT, CATEGORY_COUNTRY, CATEGORY_SITE):
		for category, ranking in get_category_rankings_by_query(
			"""
			select
				category_ranking.category,
				category_ranking.category_label,
				coalesce(cast(category_ranking.total_points_cumulated as decimal(18,6)), 0) as score
			from `tabCompetition Category Ranking` category_ranking
			where category_ranking.game = %(game)s
				and category_ranking.category_type = %(category_type)s
			""",
			{"game": game.name, "category_type": category_type},
		).items():
			rankings[(category_type, category)] = ranking
	return rankings


def update_department_ranking_rows(game, ranking_maps, prior_rankings):
	frappe.db.sql(
		"""
		update `tabCompetition Department Ranking`
		set prior_ranking = 0, ranking = 0
		where game = %(game)s
		""",
		{"game": game.name},
	)
	for (department, user), ranking in ranking_maps.items():
		frappe.db.set_value(
			"Competition Department Ranking",
			f"{department} - {game.name} - {user}",
			{
				"prior_ranking": prior_rankings.get((department, user), 0),
				"ranking": ranking,
			},
			update_modified=False,
		)


def update_category_ranking_rows(game, ranking_maps, prior_rankings):
	for (category_type, category), ranking in ranking_maps.items():
		frappe.db.set_value(
			"Competition Category Ranking",
			f"{category_type} - {category} - {game.name}",
			{
				"prior_ranking": prior_rankings.get((category_type, category), 0),
				"ranking": ranking,
			},
			update_modified=False,
		)


def get_legacy_department_ranking_map(ranking_maps):
	rankings = {}
	for (department, user), ranking in sorted(ranking_maps.items()):
		rankings.setdefault(user, ranking)
	return rankings


def get_rankings_by_query(query, params):
	rows = frappe.db.sql(
		f"""
		{query}
		order by score desc, user_full_name asc, user asc
		""",
		params,
		as_dict=True,
	)
	result = {}
	rank = 0
	prev_score = None
	for index, row in enumerate(rows, start=1):
		if prev_score is None or row.score != prev_score:
			rank = index
			prev_score = row.score
		result[row.user] = rank
	return result


def get_category_rankings_by_query(query, params):
	rows = frappe.db.sql(
		f"""
		{query}
		order by score desc, category_label asc, category asc
		""",
		params,
		as_dict=True,
	)
	result = {}
	rank = 0
	prev_score = None
	for index, row in enumerate(rows, start=1):
		if prev_score is None or row.score != prev_score:
			rank = index
			prev_score = row.score
		result[row.category] = rank
	return result


def recalc_all_rankings():
	games = frappe.db.sql(
		"""
		select game.name, game.game_id, game.competition, game.start_time
		from `tabCompetition Game` game
		inner join `tabCompetition` competition on competition.name = game.competition
		where game.validated = 1
			and competition.open = 1
		order by game.start_time asc, cast(game.game_id as unsigned) asc, game.name asc
		""",
		as_dict=True,
	)
	results = []
	for game in games:
		result = update_game_ranking_placeholder(game)
		results.append(f"Game #{game.game_id} ({game.name}): {result['rankings']} ranking(s)")
	frappe.db.commit()
	return results


def recalc_all_points_factors_and_rankings(competition=None, commit=True):
	games = get_recalculable_competition_games(competition=competition)
	summary = {"games": 0, "picks": 0, "rankings": 0, "skipped": 0}
	results = []

	for game in games:
		if is_score_pending(game):
			summary["skipped"] += 1
			results.append(f"Game #{game.game_id} ({game.name}): skipped, pending score")
			continue

		result = recalculate_competition_game(game)
		frappe.db.set_value(
			"Competition Game",
			game.name,
			{"validated": 1},
			update_modified=False,
		)
		summary["games"] += 1
		summary["picks"] += result["picks"]
		summary["rankings"] += result["rankings"]
		summary["skipped"] += result["skipped"]
		results.append(
			f"Game #{game.game_id} ({game.name}): "
			f"{result['picks']} pick(s), {result['rankings']} ranking(s)"
		)

	if cint(commit):
		frappe.db.commit()

	return {"summary": summary, "results": results}


def get_recalculable_competition_games(competition=None):
	conditions = ["game.score_updated = 1"]
	params = {}
	if competition:
		conditions.append("game.competition = %(competition)s")
		params["competition"] = competition

	return frappe.db.sql(
		f"""
		select
			game.name,
			game.game_id,
			game.competition,
			game.round,
			game.start_time,
			game.score_a,
			game.score_b,
			game.score_updated
		from `tabCompetition Game` game
		where {' and '.join(conditions)}
		order by game.competition asc, game.start_time asc, cast(game.game_id as unsigned) asc, game.name asc
		""",
		params,
		as_dict=True,
	)


def create_new_subscription_picks():
	subscriptions = frappe.get_all(
		"Competition Subscription",
		filters={"new_subscription": 1},
		fields=["name", "competition", "user"],
	)

	for subscription in subscriptions:
		games = frappe.get_all(
			"Competition Game",
			filters={"competition": subscription.competition, "open": 1},
			pluck="name",
		)

		created_picks = 0
		for game in games:
			if frappe.db.exists(
				"Competition Pick",
				{
					"competition": subscription.competition,
					"user": subscription.user,
					"game": game,
				},
			):
				continue

			frappe.get_doc(
				{
					"doctype": "Competition Pick",
					"competition": subscription.competition,
					"user": subscription.user,
					"game": game,
					"open": 1,
				}
			).insert(ignore_permissions=True)
			created_picks += 1

		frappe.db.set_value(
			"Competition Subscription",
			subscription.name,
			"new_subscription",
			0,
			update_modified=False,
		)

		if created_picks:
			frappe.enqueue(alert_new_picks_to_input, user=subscription.user)


def get_website_app_name():
	return frappe.db.get_single_value("Website Settings", "app_name") or "Football SNI"


def send_daily_pick_reminders():
	for user in get_users_with_incomplete_open_picks():
		frappe.enqueue(send_pick_reminder_to_input, user=user)


def get_users_with_incomplete_open_picks():
	return frappe.db.sql_list(
		"""
		select distinct cp.user
		from `tabCompetition Pick` cp
		inner join `tabCompetition Game` cg on cg.name = cp.game
		inner join `tabCompetition Subscription` subscription
			on subscription.user = cp.user
			and subscription.competition = cp.competition
		inner join `tabUser` user on user.name = cp.user
		where cp.open = 1
			and user.enabled = 1
			and coalesce(subscription.stop_subscription, 0) = 0
			and cg.start_time is not null
			and cg.start_time >= %(start_time_from)s
			and cg.start_time <= %(start_time_to)s
			and (
				cp.pick_a is null
				or cp.pick_a = ''
				or cp.pick_a = 'null'
				or cp.pick_b is null
				or cp.pick_b = ''
				or cp.pick_b = 'null'
			)
		order by cp.user
		""",
		get_pick_reminder_window_params(),
	)


def get_pick_reminder_window_params():
	start_time_from = now_datetime()
	return {
		"start_time_from": start_time_from,
		"start_time_to": add_to_date(start_time_from, days=PICK_REMINDER_UPCOMING_DAYS),
	}


def alert_new_picks_to_input(user):
	picks = get_available_picks(user)
	if not picks:
		return

	recipient = frappe.db.get_value("User", user, "email") or user
	if not recipient:
		return

	template = ensure_available_picks_email_template()
	context = {
		"user": user,
		"picks": picks,
		"my_picks_url": get_url("/my_picks"),
		"app_name": get_website_app_name(),
	}
	email = template.get_formatted_email(context)

	frappe.sendmail(
		recipients=[recipient],
		subject=email["subject"],
		message=email["message"],
		reference_doctype="User",
		reference_name=user,
	)


def send_pick_reminder_to_input(user):
	picks = get_available_picks(
		user,
		upcoming_days=PICK_REMINDER_UPCOMING_DAYS,
		require_active_subscription=True,
	)
	if not picks:
		return

	recipient = frappe.db.get_value("User", user, "email") or user
	if not recipient:
		return

	template = ensure_pick_reminder_email_template()
	context = {
		"user": user,
		"picks": picks,
		"my_picks_url": get_url("/my_picks"),
		"app_name": get_website_app_name(),
	}
	email = template.get_formatted_email(context)

	frappe.sendmail(
		recipients=[recipient],
		subject=email["subject"],
		message=email["message"],
		reference_doctype="User",
		reference_name=user,
	)


def get_available_picks(user, upcoming_days=None, require_active_subscription=False):
	params = {"user": user}
	start_time_filter = ""
	subscription_join = ""
	subscription_filter = ""
	if require_active_subscription:
		subscription_join = """
		inner join `tabCompetition Subscription` subscription
			on subscription.user = cp.user
			and subscription.competition = cp.competition"""
		subscription_filter = """
			and coalesce(subscription.stop_subscription, 0) = 0"""
	if upcoming_days is not None:
		start_time_from = now_datetime()
		params.update(
			{
				"start_time_from": start_time_from,
				"start_time_to": add_to_date(start_time_from, days=upcoming_days),
			}
		)
		start_time_filter = """
			and cg.start_time is not null
			and cg.start_time >= %(start_time_from)s
			and cg.start_time <= %(start_time_to)s"""

	picks = frappe.db.sql(
		"""
		select
			cp.name,
			cp.competition,
			cp.game,
			cg.game_id,
			cg.round,
			cg.start_time,
			cg.team_a,
			team_a.image as team_a_image,
			cg.team_b,
			team_b.image as team_b_image,
			cp.pick_a,
			cp.pick_b
		from `tabCompetition Pick` cp
		left join `tabCompetition Game` cg on cg.name = cp.game
		{subscription_join}
		left join `tabCompetition Team` team_a on team_a.name = cg.team_a
		left join `tabCompetition Team` team_b on team_b.name = cg.team_b
		where cp.user = %(user)s
			and cp.open = 1
			{start_time_filter}
			{subscription_filter}
			and (
				cp.pick_a is null
				or cp.pick_a = ''
				or cp.pick_a = 'null'
				or cp.pick_b is null
				or cp.pick_b = ''
				or cp.pick_b = 'null'
			)
		order by cg.start_time, cg.game_id
		""".format(
			start_time_filter=start_time_filter,
			subscription_join=subscription_join,
			subscription_filter=subscription_filter,
		),
		params,
		as_dict=True,
	)

	user_time_zone = get_user_time_zone(user)
	for pick in picks:
		pick.start_date = get_user_start_date(pick.start_time, user_time_zone)
		pick.team_a_image_src = get_team_image_src(pick.team_a_image)
		pick.team_b_image_src = get_team_image_src(pick.team_b_image)

	return picks


def get_user_time_zone(user):
	return frappe.db.get_value("User", user, "time_zone") or get_system_timezone()


def get_user_start_date(start_time, time_zone, include_time_zone=True):
	if not start_time:
		return ""

	start_datetime = get_datetime(start_time)
	start_datetime = convert_utc_to_timezone(start_datetime, time_zone)
	start_date = format_datetime(start_datetime, 'yyyy-MM-dd HH:mm')
	if include_time_zone:
		return f"{start_date} ({time_zone})"
	return start_date


def ensure_competition_team_images_are_public():
	files = frappe.get_all(
		"File",
		filters={
			"attached_to_doctype": "Competition Team",
			"attached_to_field": "image",
		},
		fields=["name", "is_private"],
	)

	updated = 0
	for file in files:
		if file.is_private:
			frappe.db.set_value("File", file.name, "is_private", 0, update_modified=False)
			updated += 1

	return updated


def get_team_image_src(image):
	if not image:
		return ""

	if image.startswith(("http://", "https://")):
		return image

	return get_url(image)


def ensure_available_picks_email_template():
	return get_or_create_email_template(
		AVAILABLE_PICKS_TEMPLATE,
		"Your picks are ready - time to make the call!",
		AVAILABLE_PICKS_EMAIL_HTML,
	)


def ensure_pick_reminder_email_template():
	subject = "Tiny nudge: your next 3 days of picks are waiting"
	template = get_or_create_email_template(
		PICK_REMINDER_TEMPLATE,
		subject,
		PICK_REMINDER_EMAIL_HTML,
	)
	if template.subject != subject or not template.use_html or template.response_html != PICK_REMINDER_EMAIL_HTML:
		template.subject = subject
		template.use_html = 1
		template.response_html = PICK_REMINDER_EMAIL_HTML
		template.save(ignore_permissions=True)
	return template


AVAILABLE_PICKS_EMAIL_HTML = """
<div style="background: #f6f8fb; color: #162033; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; padding: 24px;">
	<div style="background: #ffffff; border: 1px solid #dde3ea; border-radius: 8px; box-shadow: 0 10px 28px rgba(22, 32, 51, 0.08); overflow: hidden;">
		<div style="background: #0f766e; color: #ffffff; padding: 18px 22px;">
			<div style="font-size: 12px; font-weight: 700; letter-spacing: 0; text-transform: uppercase;">{{ app_name }}</div>
			<div style="font-size: 24px; font-weight: 800; line-height: 1.15; margin-top: 4px;">Your picks are ready</div>
		</div>

		<div style="padding: 22px;">
			<p style="font-size: 16px; margin: 0 0 10px;">Hey {{ user }},</p>
			<p style="color: #526171; font-size: 14px; line-height: 1.55; margin: 0 0 16px;">Your next set of picks is waiting. The pitch is fresh, the matchups are ready, and now it is your turn to bring the magic.</p>

			<p style="margin: 0 0 22px;">
				<a href="{{ my_picks_url }}" style="background: #0f766e; border-radius: 8px; color: #ffffff; display: inline-block; font-weight: 700; padding: 10px 14px; text-decoration: none;">Open My Picks</a>
			</p>

			<table cellpadding="0" cellspacing="0" style="border-collapse: collapse; width: 100%;">
				<thead>
					<tr>
						<th align="left" style="background: #e8f4f2; border-bottom: 1px solid #c7d1dc; color: #0f766e; font-size: 12px; padding: 10px 8px; text-transform: uppercase;">Game ID</th>
						<th align="left" style="background: #e8f4f2; border-bottom: 1px solid #c7d1dc; color: #0f766e; font-size: 12px; padding: 10px 8px; text-transform: uppercase;">Round</th>
						<th align="left" style="background: #e8f4f2; border-bottom: 1px solid #c7d1dc; color: #0f766e; font-size: 12px; padding: 10px 8px; text-transform: uppercase;">Date</th>
						<th align="center" colspan="5" style="background: #e8f4f2; border-bottom: 1px solid #c7d1dc; color: #0f766e; font-size: 12px; padding: 10px 8px; text-transform: uppercase;">Game</th>
					</tr>
				</thead>
				<tbody>
					{% for pick in picks %}
					<tr>
						<td style="border-bottom: 1px solid #dde3ea; color: #162033; font-weight: 700; padding: 10px 8px;">{{ pick.game_id or "" }}</td>
						<td style="border-bottom: 1px solid #dde3ea; color: #526171; padding: 10px 8px;">{{ pick.round or "" }}</td>
						<td style="border-bottom: 1px solid #dde3ea; color: #526171; padding: 10px 8px; white-space: nowrap;">{{ pick.start_date or "" }}</td>
						<td align="right" style="border-bottom: 1px solid #dde3ea; color: #162033; font-weight: 700; padding: 10px 6px;">{{ pick.team_a or "" }}</td>
						<td align="center" style="border-bottom: 1px solid #dde3ea; padding: 10px 4px; width: 34px;">
							{% if pick.team_a_image_src %}
							<img src="{{ pick.team_a_image_src }}" alt="{{ pick.team_a or '' }}" style="height: 20px; max-width: 32px; vertical-align: middle;" />
							{% endif %}
						</td>
						<td align="center" style="border-bottom: 1px solid #dde3ea; color: #697789; font-weight: 800; padding: 10px 2px; width: 12px;">:</td>
						<td align="center" style="border-bottom: 1px solid #dde3ea; padding: 10px 4px; width: 34px;">
							{% if pick.team_b_image_src %}
							<img src="{{ pick.team_b_image_src }}" alt="{{ pick.team_b or '' }}" style="height: 20px; max-width: 32px; vertical-align: middle;" />
							{% endif %}
						</td>
						<td align="left" style="border-bottom: 1px solid #dde3ea; color: #162033; font-weight: 700; padding: 10px 6px;">{{ pick.team_b or "" }}</td>
					</tr>
					{% endfor %}
				</tbody>
			</table>

			<p style="color: #697789; font-size: 13px; line-height: 1.55; margin: 18px 0 0;">No pressure... except, well, eternal leaderboard glory. Have fun!</p>
		</div>
	</div>
</div>
"""


PICK_REMINDER_EMAIL_HTML = """
<div style="background: #f6f8fb; color: #162033; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; padding: 24px;">
	<div style="background: #ffffff; border: 1px solid #dde3ea; border-radius: 8px; box-shadow: 0 10px 28px rgba(22, 32, 51, 0.08); overflow: hidden;">
		<div style="background: #0f766e; color: #ffffff; padding: 18px 22px;">
			<div style="font-size: 12px; font-weight: 700; letter-spacing: 0; text-transform: uppercase;">{{ app_name }}</div>
			<div style="font-size: 24px; font-weight: 800; line-height: 1.15; margin-top: 4px;">Your picks need you</div>
		</div>

		<div style="padding: 22px;">
			<p style="font-size: 16px; margin: 0 0 10px;">Hey {{ user }},</p>
			<p style="color: #526171; font-size: 14px; line-height: 1.55; margin: 0 0 16px;">A few open picks for games in the next 3 days are still waiting for your genius. Give them a score, trust the instinct, and let the leaderboard drama begin.</p>

			<p style="margin: 0 0 22px;">
				<a href="{{ my_picks_url }}" style="background: #0f766e; border-radius: 8px; color: #ffffff; display: inline-block; font-weight: 700; padding: 10px 14px; text-decoration: none;">Complete My Picks</a>
			</p>

			<table cellpadding="0" cellspacing="0" style="border-collapse: collapse; width: 100%;">
				<thead>
					<tr>
						<th align="left" style="background: #e8f4f2; border-bottom: 1px solid #c7d1dc; color: #0f766e; font-size: 12px; padding: 10px 8px; text-transform: uppercase;">Game ID</th>
						<th align="left" style="background: #e8f4f2; border-bottom: 1px solid #c7d1dc; color: #0f766e; font-size: 12px; padding: 10px 8px; text-transform: uppercase;">Round</th>
						<th align="left" style="background: #e8f4f2; border-bottom: 1px solid #c7d1dc; color: #0f766e; font-size: 12px; padding: 10px 8px; text-transform: uppercase;">Date</th>
						<th align="center" colspan="5" style="background: #e8f4f2; border-bottom: 1px solid #c7d1dc; color: #0f766e; font-size: 12px; padding: 10px 8px; text-transform: uppercase;">Game</th>
					</tr>
				</thead>
				<tbody>
					{% for pick in picks %}
					<tr>
						<td style="border-bottom: 1px solid #dde3ea; color: #162033; font-weight: 700; padding: 10px 8px;">{{ pick.game_id or "" }}</td>
						<td style="border-bottom: 1px solid #dde3ea; color: #526171; padding: 10px 8px;">{{ pick.round or "" }}</td>
						<td style="border-bottom: 1px solid #dde3ea; color: #526171; padding: 10px 8px; white-space: nowrap;">{{ pick.start_date or "" }}</td>
						<td align="right" style="border-bottom: 1px solid #dde3ea; color: #162033; font-weight: 700; padding: 10px 6px;">{{ pick.team_a or "" }}</td>
						<td align="center" style="border-bottom: 1px solid #dde3ea; padding: 10px 4px; width: 34px;">
							{% if pick.team_a_image_src %}
							<img src="{{ pick.team_a_image_src }}" alt="{{ pick.team_a or '' }}" style="height: 20px; max-width: 32px; vertical-align: middle;" />
							{% endif %}
						</td>
						<td align="center" style="border-bottom: 1px solid #dde3ea; color: #697789; font-weight: 800; padding: 10px 2px; width: 12px;">:</td>
						<td align="center" style="border-bottom: 1px solid #dde3ea; padding: 10px 4px; width: 34px;">
							{% if pick.team_b_image_src %}
							<img src="{{ pick.team_b_image_src }}" alt="{{ pick.team_b or '' }}" style="height: 20px; max-width: 32px; vertical-align: middle;" />
							{% endif %}
						</td>
						<td align="left" style="border-bottom: 1px solid #dde3ea; color: #162033; font-weight: 700; padding: 10px 6px;">{{ pick.team_b or "" }}</td>
					</tr>
					{% endfor %}
				</tbody>
			</table>

			<p style="color: #697789; font-size: 13px; line-height: 1.55; margin: 18px 0 0;">No pressure... except, well, the very official business of proving your football instincts are elite. Have fun!</p>
		</div>
	</div>
</div>
"""
