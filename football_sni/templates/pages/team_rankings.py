from urllib.parse import urlencode

import frappe
from frappe import _

from football_sni.templates.pages.game_result import format_number
from football_sni.templates.pages.rankings import RANKINGS_CACHE_SECONDS, get_ranking_games, get_rankings_cache_key, get_selected_game
from football_sni.website import add_user_settings_context, require_user_location


FILTER_COUNTRY = "country"
FILTER_SITE = "site"
FILTER_TEAM = "team"


CATEGORY_TYPES = {
	FILTER_COUNTRY: "Country",
	FILTER_SITE: "Site",
	FILTER_TEAM: "Department",
}


CATEGORY_LABELS = {
	FILTER_COUNTRY: _("Country"),
	FILTER_SITE: _("Site"),
	FILTER_TEAM: _("Team"),
}


def get_context(context):
	require_user_location("/team_rankings")
	add_user_settings_context(context)
	context.no_cache = 1
	context.show_sidebar = 0
	context.full_width = 1
	context.body_class = "fsni-site"
	context.title = _("Team Rankings")

	context.games = get_ranking_games()
	context.selected_game = get_selected_game(context.games)
	context.filter_mode = get_filter_mode()
	context.category_label = CATEGORY_LABELS[context.filter_mode]
	context.rankings = get_team_rankings(context.selected_game, context.filter_mode)


def get_filter_mode():
	filter_mode = frappe.form_dict.get("filter") or FILTER_COUNTRY
	return filter_mode if filter_mode in CATEGORY_TYPES else FILTER_COUNTRY


def get_team_rankings(selected_game, filter_mode):
	if not selected_game or not selected_game.validated:
		return []
	if not frappe.db.table_exists("Competition Category Ranking"):
		return []

	cache_key = get_team_rankings_cache_key(selected_game, filter_mode)
	rows = frappe.cache().get_value(cache_key)
	if rows is None:
		rows = get_team_ranking_rows(selected_game, filter_mode)
		frappe.cache().set_value(cache_key, rows, expires_in_sec=RANKINGS_CACHE_SECONDS)

	return prepare_team_ranking_rows(rows, selected_game, filter_mode)


def get_team_ranking_rows(selected_game, filter_mode):
	return frappe.db.sql(
		"""
		select
			category_ranking.category,
			category_ranking.category_label,
			category_ranking.ranking,
			category_ranking.users_count,
			category_ranking.total_points,
			category_ranking.total_points_cumulated,
			site.country as site_country,
			site.site as site_name
		from `tabCompetition Category Ranking` category_ranking
		left join `tabFNSI Site` site on site.name = category_ranking.category
		where category_ranking.game = %(game)s
			and category_ranking.category_type = %(category_type)s
			and category_ranking.ranking > 0
		order by category_ranking.ranking asc, category_ranking.category_label asc, category_ranking.category asc
		""",
		{
			"game": selected_game.name,
			"category_type": CATEGORY_TYPES[filter_mode],
		},
		as_dict=True,
	)


def prepare_team_ranking_rows(rows, selected_game, filter_mode):
	prepared_rows = []
	for row in rows:
		row = frappe._dict(row.copy())
		row.total_points_raw = (row.total_points or 0) * (row.users_count or 0)
		row.total_points_raw_display = format_number(row.total_points_raw, decimals=3)
		row.points_display = format_number(row.total_points, decimals=3)
		row.total_points_cumulated_display = format_number(row.total_points_cumulated, decimals=3)
		row.game_results_url = get_game_results_url(selected_game, filter_mode, row)
		prepared_rows.append(row)
	return prepared_rows


def get_team_rankings_cache_key(selected_game, filter_mode):
	return get_rankings_cache_key("team_rows", selected_game.name, filter_mode)


def get_game_results_url(selected_game, filter_mode, row):
	params = {
		"game": selected_game.name,
		"filter": "general",
	}
	if filter_mode == FILTER_COUNTRY:
		params["country"] = row.category
	elif filter_mode == FILTER_SITE:
		params["country"] = row.site_country or ""
		params["city"] = row.site_name or row.category_label or row.category
	elif filter_mode == FILTER_TEAM:
		params["list_department"] = row.category
	return "/game_result?" + urlencode(params)
