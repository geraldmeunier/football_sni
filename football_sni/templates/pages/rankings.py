from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils import flt

from football_sni.templates.pages.game_result import (
	FILTER_DEPARTMENT,
	FILTER_GENERAL,
	FILTER_SITE,
	format_number,
	get_current_department,
	get_current_departments,
	get_favorite_members,
	get_list_filter_options,
	get_list_filters,
)
from football_sni.website import add_user_settings_context, get_current_user_location, require_user_location


RANKING_FIELDS = {
	FILTER_GENERAL: ("ranking", "prior_ranking", "total_points_cumulated"),
	FILTER_SITE: ("ranking_site", "prior_ranking_site", "total_points_site_cumulated"),
	FILTER_DEPARTMENT: ("ranking_department", "prior_ranking_department", "total_points_department_cumulated"),
}


def get_context(context):
	require_user_location("/rankings")
	add_user_settings_context(context)
	context.no_cache = 1
	context.show_sidebar = 0
	context.full_width = 1
	context.body_class = "fsni-site"
	context.title = _("Rankings")

	context.games = get_ranking_games()
	context.selected_game = get_selected_game(context.games)
	context.selected_competition = context.selected_game.competition if context.selected_game else ""
	context.filter_mode = get_filter_mode()
	context.current_user_site = get_current_user_location()
	context.current_departments = get_current_departments(context.selected_competition)
	context.current_department = get_current_department(context.selected_competition, context.current_departments)
	if context.filter_mode == FILTER_SITE and not context.current_user_site:
		context.filter_mode = FILTER_GENERAL
	if context.filter_mode == FILTER_DEPARTMENT and not context.current_department:
		context.filter_mode = FILTER_GENERAL

	context.only_favorites = frappe.form_dict.get('favorites') in ('1', 'true', 'yes')
	context.favorite_members = get_favorite_members(context.selected_competition, frappe.session.user)
	context.list_filters = get_list_filters(context.selected_game, context.filter_mode)
	context.list_filter_options = get_list_filter_options(context.selected_game)
	context.rankings = get_rankings(
		context.selected_competition,
		context.selected_game,
		context.filter_mode,
		context.current_user_site,
		context.current_department,
		context.favorite_members,
		context.only_favorites,
		context.list_filters,
	)
	context.query_base = get_query_base(context.selected_game, context.list_filters)


def get_ranking_games():
	validated_games = frappe.db.sql(
		"""
		select game.name, game.game_id, game.team_a, game.team_b, game.competition, game.start_time, game.validated
		from `tabCompetition Game` game
		inner join `tabCompetition` competition on competition.name = game.competition
		where competition.open = 1
			and game.validated = 1
		order by game.start_time desc, cast(game.game_id as unsigned) desc, game.name desc
		""",
		as_dict=True,
	)
	if validated_games:
		return validated_games

	return frappe.db.sql(
		"""
		select game.name, game.game_id, game.team_a, game.team_b, game.competition, game.start_time, game.validated
		from `tabCompetition Game` game
		inner join `tabCompetition` competition on competition.name = game.competition
		where competition.open = 1
			and game.open = 1
		order by game.start_time asc, cast(game.game_id as unsigned) asc, game.name asc
		""",
		as_dict=True,
	)


def get_selected_game(games):
	selected = frappe.form_dict.get("game")
	for game in games:
		if game.name == selected:
			return game
	return games[0] if games else None


def get_filter_mode():
	filter_mode = frappe.form_dict.get("filter") or FILTER_GENERAL
	return filter_mode if filter_mode in RANKING_FIELDS else FILTER_GENERAL


def get_competition_pick_field(fieldname, fallback='total_points_cumulated'):
	if frappe.db.has_column('Competition Pick', fieldname):
		return fieldname
	return fallback


def apply_general_list_filters(conditions, params, list_filters, user_reference="ranking.user"):
	if list_filters.get("country") or list_filters.get("city"):
		conditions.append(
			"""exists (
				select 1
				from `tabFNSI Site` site
				where site.name = user.location
					and (%(country)s = '' or site.country = %(country)s)
					and (%(city)s = '' or site.site = %(city)s)
			)"""
		)
		params["country"] = list_filters.get("country") or ""
		params["city"] = list_filters.get("city") or ""
	if list_filters.get("department"):
		conditions.append(
			f"""exists (
				select 1
				from `tabFNSI User Department` user_department
				where user_department.user = {user_reference}
					and user_department.department = %(list_department)s
					and user_department.status = 'Validated'
			)"""
		)
		params["list_department"] = list_filters.department


def get_rankings(competition, selected_game, filter_mode, current_user_site, current_department, favorite_members=None, only_favorites=False, list_filters=None):
	if not competition or not selected_game:
		return []

	if not selected_game.validated:
		return get_open_game_players(
			competition,
			selected_game,
			filter_mode,
			current_user_site,
			current_department,
			favorite_members,
			only_favorites,
			list_filters,
		)

	favorite_members = favorite_members or set()
	ranking_field_name, prior_ranking_field_name, cumulative_field = RANKING_FIELDS[filter_mode]
	ranking_field = f"ranking.{ranking_field_name}"
	prior_ranking_field = f"ranking.{prior_ranking_field_name}"
	conditions = [f"{ranking_field} > 0"]
	params = {
		"competition": competition,
		"game": selected_game.name,
	}
	department_join = ''
	points_expression = f"pick.`{get_competition_pick_field(cumulative_field)}`"

	if filter_mode == FILTER_SITE:
		if not current_user_site:
			return []
		conditions.append("user.location = %(site)s")
		params["site"] = current_user_site
	elif filter_mode == FILTER_DEPARTMENT:
		if not current_department:
			return []
		department_join = """
		inner join `tabCompetition Department Ranking` department_ranking
			on department_ranking.game = ranking.game
			and department_ranking.user = ranking.user
			and department_ranking.department = %(department)s
		"""
		ranking_field = "department_ranking.ranking"
		prior_ranking_field = "department_ranking.prior_ranking"
		points_expression = "department_ranking.total_points_cumulated"
		conditions = ["department_ranking.ranking > 0"]
		params["department"] = current_department.name

	if filter_mode == FILTER_GENERAL and list_filters:
		apply_general_list_filters(conditions, params, list_filters)

	if only_favorites:
		if not favorite_members:
			return []
		conditions.append("ranking.user in %(favorite_members)s")
		params["favorite_members"] = tuple(favorite_members)

	rows = frappe.db.sql(
		f"""
		select
			ranking.user,
			coalesce(nullif(user.full_name, ''), user.name) as user_full_name,
			coalesce(site.country, '') as country,
			coalesce(site.site, '') as site,
			{ranking_field} as ranking,
			{prior_ranking_field} as prior_ranking,
			{points_expression} as total_points_cumulated,
			coalesce((
				select sum(cp2.exact_result)
				from `tabCompetition Pick` cp2
				inner join `tabCompetition Game` cg2 on cg2.name = cp2.game
				where cp2.competition = %(competition)s
					and cp2.user = ranking.user
					and cp2.not_played = 0
					and cg2.validated = 1
			), 0) as total_exact_result,
			coalesce((
				select sum(cp2.good_difference)
				from `tabCompetition Pick` cp2
				inner join `tabCompetition Game` cg2 on cg2.name = cp2.game
				where cp2.competition = %(competition)s
					and cp2.user = ranking.user
					and cp2.not_played = 0
					and cg2.validated = 1
			), 0) as total_good_difference,
			coalesce((
				select sum(cp2.good_trend)
				from `tabCompetition Pick` cp2
				inner join `tabCompetition Game` cg2 on cg2.name = cp2.game
				where cp2.competition = %(competition)s
					and cp2.user = ranking.user
					and cp2.not_played = 0
					and cg2.validated = 1
			), 0) as total_good_trend
		from `tabCompetition Ranking` ranking
		inner join `tabUser` user on user.name = ranking.user
		left join `tabFNSI Site` site on site.name = user.location
		left join `tabCompetition Pick` pick on pick.game = ranking.game and pick.user = ranking.user
		{department_join}
		where ranking.competition = %(competition)s
			and ranking.game = %(game)s
			and {' and '.join(conditions)}
		order by {ranking_field} asc, user_full_name asc, ranking.user asc
		""",
		params,
		as_dict=True,
	)

	for row in rows:
		row.is_favorite = row.user in favorite_members
		row.total_points_cumulated_display = format_number(row.total_points_cumulated, decimals=3)
		row.move = get_ranking_move(row.prior_ranking, row.ranking)
	return rows


def get_open_game_players(competition, selected_game, filter_mode, current_user_site, current_department, favorite_members=None, only_favorites=False, list_filters=None):
	favorite_members = favorite_members or set()
	conditions = ["pick.competition = %(competition)s", "pick.game = %(game)s"]
	params = {
		"competition": competition,
		"game": selected_game.name,
	}
	joins = []

	if filter_mode == FILTER_SITE:
		if not current_user_site:
			return []
		conditions.append("user.location = %(site)s")
		params["site"] = current_user_site
	elif filter_mode == FILTER_DEPARTMENT:
		if not current_department:
			return []
		joins.append(
			"""inner join `tabFNSI User Department` selected_department
				on selected_department.user = pick.user
				and selected_department.department = %(department)s
				and selected_department.status = 'Validated'"""
		)
		params["department"] = current_department.name

	if filter_mode == FILTER_GENERAL and list_filters:
		apply_general_list_filters(conditions, params, list_filters, user_reference="pick.user")

	if only_favorites:
		if not favorite_members:
			return []
		conditions.append("pick.user in %(favorite_members)s")
		params["favorite_members"] = tuple(favorite_members)

	rows = frappe.db.sql(
		f"""
		select distinct
			pick.user,
			coalesce(nullif(user.full_name, ''), user.name) as user_full_name,
			coalesce(site.country, '') as country,
			coalesce(site.site, '') as site,
			0 as ranking,
			0 as prior_ranking,
			0 as total_points_cumulated,
			0 as total_exact_result,
			0 as total_good_difference,
			0 as total_good_trend
		from `tabCompetition Pick` pick
		inner join `tabUser` user on user.name = pick.user
		left join `tabFNSI Site` site on site.name = user.location
		{' '.join(joins)}
		where {' and '.join(conditions)}
		order by user_full_name asc, pick.user asc
		""",
		params,
		as_dict=True,
	)

	for row in rows:
		row.ranking = ""
		row.is_favorite = row.user in favorite_members
		row.total_points_cumulated_display = ""
		row.move = ""
	return rows


def get_ranking_move(prior_ranking, ranking):
	prior_ranking = flt(prior_ranking)
	ranking = flt(ranking)
	if not prior_ranking:
		return ""
	move = int(prior_ranking - ranking)
	if move > 0:
		return f"+{move}"
	if move < 0:
		return str(move)
	return "="


def get_query_base(selected_game, list_filters=None):
	if not selected_game:
		return ""
	params = ["game=" + quote(selected_game.name, safe="")]
	if list_filters:
		if list_filters.country:
			params.append("country=" + quote(list_filters.country, safe=""))
		if list_filters.city:
			params.append("city=" + quote(list_filters.city, safe=""))
		if list_filters.department:
			params.append("list_department=" + quote(list_filters.department, safe=""))
	return "&".join(params)
