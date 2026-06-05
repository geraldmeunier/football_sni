from urllib.parse import quote

import frappe
from frappe import _

from frappe.utils import cint, convert_utc_to_timezone, flt, format_datetime, get_datetime

from football_sni.tasks import get_user_time_zone
from football_sni.templates.pages.game_result import FILTER_DEPARTMENT, FILTER_GENERAL, FILTER_SITE
from football_sni.website import add_user_settings_context, get_current_user_location, require_user_location


FACTOR_FIELDS = {
	FILTER_GENERAL: 'factor',
	FILTER_SITE: 'factor_site',
	FILTER_DEPARTMENT: 'factor_department',
}

TOTAL_POINTS_FIELDS = {
	FILTER_GENERAL: 'total_points',
	FILTER_SITE: 'total_points_site',
	FILTER_DEPARTMENT: 'total_points_department',
}

TOTAL_POINTS_CUMULATED_FIELDS = {
	FILTER_GENERAL: 'total_points_cumulated',
	FILTER_SITE: 'total_points_site_cumulated',
	FILTER_DEPARTMENT: 'total_points_department_cumulated',
}

RANKING_FIELDS = {
	FILTER_GENERAL: ('ranking', 'prior_ranking'),
	FILTER_SITE: ('ranking_site', 'prior_ranking_site'),
	FILTER_DEPARTMENT: ('ranking_department', 'prior_ranking_department'),
}


def get_context(context):
	require_user_location('/my_picks')
	add_user_settings_context(context)
	context.no_cache = 1
	context.show_sidebar = 0
	context.full_width = 1
	context.body_class = 'fsni-site'
	context.title = _('Picks')
	context.user_time_zone = get_user_time_zone(frappe.session.user)
	context.filter_mode = get_filter_mode()
	context.current_user_site = get_current_user_location()
	context.players = get_pick_players()
	context.selected_user = get_selected_user(context.players)
	context.viewing_own_picks = context.selected_user == frappe.session.user
	context.selected_user_full_name = get_player_display_name(context.players, context.selected_user)
	context.current_departments = get_user_departments(context.selected_user)
	context.current_department = get_selected_department(context.current_departments)
	if context.filter_mode == FILTER_DEPARTMENT and not context.current_department:
		context.filter_mode = FILTER_GENERAL
	context.user_query_suffix = get_user_query_suffix(context.selected_user)
	context.department_query_suffix = get_department_query_suffix(context.current_department)
	context.picks = get_my_picks(context.user_time_zone, context.filter_mode, context.selected_user, context.current_department)


def get_filter_mode():
	filter_mode = frappe.form_dict.get('filter') or FILTER_GENERAL
	return filter_mode if filter_mode in FACTOR_FIELDS else FILTER_GENERAL


def get_user_departments(user):
	return frappe.db.sql(
		'''
		select department.name, department.team, department.competition
		from `tabFNSI User Department` user_department
		inner join `tabFNSI Department` department on department.name = user_department.department
		where user_department.user = %(user)s
			and user_department.status = 'Validated'
		order by department.team asc, department.name asc
		''',
		{'user': user},
		as_dict=True,
	)


def get_selected_department(departments):
	selected_department = frappe.form_dict.get('department')
	for department in departments:
		if department.name == selected_department:
			return department
	return departments[0] if departments else None


def get_department_query_suffix(department):
	if not department:
		return ''
	return '&department=' + quote(department.name, safe='')


def get_pick_players():
	return frappe.db.sql(
		'''
		select distinct
			cp.user,
			coalesce(nullif(user.full_name, ''), user.name) as user_full_name
		from `tabCompetition Pick` cp
		inner join `tabUser` user on user.name = cp.user
		order by user_full_name asc, cp.user asc
		''',
		as_dict=True,
	)


def get_selected_user(players):
	selected_user = frappe.form_dict.get('user') or frappe.session.user
	player_names = {player.user for player in players}
	if selected_user in player_names:
		return selected_user
	return frappe.session.user


def get_player_display_name(players, user):
	for player in players:
		if player.user == user:
			return player.user_full_name
	return user


def get_user_query_suffix(user):
	if not user or user == frappe.session.user:
		return ''
	return '&user=' + quote(user, safe='')


def get_competition_pick_field(fieldname, fallback='total_points_cumulated'):
	if frappe.db.has_column('Competition Pick', fieldname):
		return fieldname
	return fallback


def get_my_picks(user_time_zone=None, filter_mode=FILTER_GENERAL, user=None, current_department=None):
	user = user or frappe.session.user
	viewing_own_picks = user == frappe.session.user
	factor_field = f"cp.{FACTOR_FIELDS.get(filter_mode, 'factor')}"
	total_points_field = f"cp.`{get_competition_pick_field(TOTAL_POINTS_FIELDS.get(filter_mode, 'total_points'), 'total_points')}`"
	total_points_cumulated_field = f"cp.`{get_competition_pick_field(TOTAL_POINTS_CUMULATED_FIELDS.get(filter_mode, 'total_points_cumulated'))}`"
	ranking_field, prior_ranking_field = RANKING_FIELDS.get(filter_mode, RANKING_FIELDS[FILTER_GENERAL])
	ranking_field = f"ranking.{ranking_field}"
	prior_ranking_field = f"ranking.{prior_ranking_field}"
	department_join = ''
	conditions = ['cp.user = %(user)s']
	if not viewing_own_picks:
		conditions.append('cg.do_not_show = 0')
	params = {'user': user}
	if filter_mode == FILTER_DEPARTMENT:
		if not current_department:
			return []
		department_join = '''
		left join `tabCompetition Department Ranking` department_ranking
			on department_ranking.game = cp.game
			and department_ranking.user = cp.user
			and department_ranking.department = %(department)s
		'''
		conditions.append('cp.competition = %(department_competition)s')
		factor_field = 'department_ranking.factor'
		total_points_field = 'department_ranking.total_points'
		total_points_cumulated_field = 'department_ranking.total_points_cumulated'
		ranking_field = 'department_ranking.ranking'
		prior_ranking_field = 'department_ranking.prior_ranking'
		params['department'] = current_department.name
		params['department_competition'] = current_department.competition

	rows = frappe.db.sql(
		f'''
		select
			cp.name,
			cp.competition,
			cp.game,
			cp.open,
			cg.open as game_open,
			cp.pick_a,
			cp.pick_b,
			cg.game_id,
			cg.round,
			cg.start_time,
			cg.score_a,
			cg.score_b,
			cg.score_updated,
			cg.team_a,
			team_a.image as team_a_image,
			team_a.image_url as team_a_image_url,
			cg.team_b,
			team_b.image as team_b_image,
			team_b.image_url as team_b_image_url,
			cp.exact_result,
			cp.good_difference,
			cp.good_trend,
			cp.points,
			cp.coefficient,
			{factor_field} as factor,
			{total_points_field} as total_points,
			{total_points_cumulated_field} as total_points_cumulated,
			{ranking_field} as ranking,
			{prior_ranking_field} as prior_ranking
		from `tabCompetition Pick` cp
		left join `tabCompetition Game` cg on cg.name = cp.game
		left join `tabCompetition Team` team_a on team_a.name = cg.team_a
		left join `tabCompetition Team` team_b on team_b.name = cg.team_b
		left join `tabCompetition Ranking` ranking on ranking.game = cp.game and ranking.user = cp.user
		{department_join}
		where {' and '.join(conditions)}
		order by cast(cg.game_id as unsigned), cg.game_id
		''',
		params,
		as_dict=True,
	)

	user_time_zone = user_time_zone or get_user_time_zone(user)
	previous_round = None
	previous_date = None

	for row in rows:
		row.start_date = get_pick_date(row.start_time, user_time_zone)
		row.display_round = row.round if row.round != previous_round else ''
		row.display_date = row.start_date if row.start_date != previous_date else ''
		row.team_a_image_src = get_team_image_src(row.team_a_image, row.team_a_image_url)
		row.team_b_image_src = get_team_image_src(row.team_b_image, row.team_b_image_url)
		row.pick_is_open = cint(row.open) == 1
		row.game_is_open = cint(row.game_open) == 1
		row.is_open = row.pick_is_open and row.game_is_open
		row.has_score_updated = cint(row.score_updated) == 1
		row.can_edit = viewing_own_picks and row.is_open
		row.has_result = not row.game_is_open and row.has_score_updated
		row.has_score = row.has_result and row.score_a not in (None, '') and row.score_b not in (None, '')
		row.score_a_display = row.score_a if row.has_score else ''
		row.score_b_display = row.score_b if row.has_score else ''
		row.exact_result_display = row.exact_result if row.has_result and row.exact_result else ''
		row.good_difference_display = row.good_difference if row.has_result and row.good_difference else ''
		row.good_trend_display = row.good_trend if row.has_result and row.good_trend else ''
		row.points_display = format_number(row.points, decimals=0) if row.has_result else ''
		row.coefficient_display = format_number(row.coefficient, decimals=0) if row.has_result else ''
		row.factor_display = format_number(row.factor, decimals=3) if row.has_result else ''
		row.total_points_display = format_number(row.total_points, decimals=3) if row.has_result else ''
		row.total_points_cumulated_display = format_number(row.total_points_cumulated, decimals=3) if row.has_result else ''
		row.ranking_display = get_ranking_display(row.ranking) if row.has_result else ''
		row.ranking_move = get_ranking_move(row.prior_ranking, row.ranking) if row.has_result else ''
		row.ranking_move_class = get_ranking_move_class(row.ranking_move)
		row.result_url = get_result_url(row.game, filter_mode, current_department)

		previous_round = row.round
		previous_date = row.start_date

	return rows


def get_pick_date(start_time, time_zone):
	if not start_time:
		return ''

	start_datetime = get_datetime(start_time)
	start_datetime = convert_utc_to_timezone(start_datetime, time_zone)
	return format_datetime(start_datetime, 'yyyy-MM-dd')


def get_team_image_src(image, image_url):
	return image or image_url or ''


def format_number(value, decimals=None):
	if value in (None, ''):
		return ''
	value = flt(value)
	if decimals is None:
		if value == int(value):
			return str(int(value))
		return f'{value:.2f}'.rstrip('0').rstrip('.')
	if decimals == 0:
		return str(int(round(value)))
	return f'{value:.{decimals}f}'


def get_result_url(game, filter_mode=FILTER_GENERAL, department=None):
	params = ['game=' + quote(game or '', safe='')]
	if filter_mode:
		params.append('filter=' + quote(filter_mode, safe=''))
	if department:
		params.append('department=' + quote(department.name, safe=''))
	return '/game_result?' + '&'.join(params)


def get_ranking_display(ranking):
	if ranking in (None, '', 0):
		return ''
	return str(int(flt(ranking)))


def get_ranking_move(prior_ranking, ranking):
	prior_ranking = flt(prior_ranking)
	ranking = flt(ranking)
	if not prior_ranking or not ranking:
		return ''
	if ranking < prior_ranking:
		return 'up'
	if ranking > prior_ranking:
		return 'down'
	return 'same'


def get_ranking_move_class(move):
	if move == 'up':
		return 'fsni-ranking-up'
	if move == 'down':
		return 'fsni-ranking-down'
	if move == 'same':
		return 'fsni-ranking-same'
	return ''
