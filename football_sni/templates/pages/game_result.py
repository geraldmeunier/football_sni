from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils import flt

from football_sni.website import add_user_settings_context, get_current_user_location, require_user_location


FILTER_GENERAL = 'general'
FILTER_SITE = 'site'
FILTER_DEPARTMENT = 'department'


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


TOTAL_POINTS_CUMULATED_HELP = {
	FILTER_GENERAL: _('Cumulated total points for the general leaderboard.'),
	FILTER_SITE: _('Cumulated total points for your site leaderboard.'),
	FILTER_DEPARTMENT: _('Cumulated total points for your department leaderboard.'),
}


SORT_FIELDS = {
	'user': 'user_full_name',
	'pick_a': 'cast(pick.pick_a as signed)',
	'pick_b': 'cast(pick.pick_b as signed)',
	'points': 'cast(pick.points as decimal(18,6))',
	'exact_result': 'cast(pick.exact_result as signed)',
	'good_difference': 'cast(pick.good_difference as signed)',
	'good_trend': 'cast(pick.good_trend as signed)',
	'coefficient': 'cast(pick.coefficient as decimal(18,6))',
	'factor': 'cast({factor_field} as decimal(18,6))',
	'total_points': 'cast({total_points_field} as decimal(18,6))',
	'total_points_cumulated': 'cast({total_points_cumulated_field} as decimal(18,6))',
}


def get_context(context):
	require_user_location('/game_result')
	add_user_settings_context(context)
	context.no_cache = 1
	context.show_sidebar = 0
	context.full_width = 1
	context.body_class = 'fsni-site'
	context.title = _('Game Result')

	context.games = get_closed_games()
	context.game = get_selected_game(context.games)
	context.result_game = get_result_game(context.game)
	context.filter_mode = get_filter_mode()
	context.only_favorites = frappe.form_dict.get('favorites') in ('1', 'true', 'yes')
	context.current_user_site = get_current_user_location()
	context.current_departments = get_current_departments(context.result_game.competition if context.result_game else None)
	context.current_department = get_current_department(context.result_game.competition if context.result_game else None, context.current_departments)
	if context.filter_mode == FILTER_DEPARTMENT and not context.current_department:
		context.filter_mode = FILTER_GENERAL
	context.total_points_cumulated_help = TOTAL_POINTS_CUMULATED_HELP[context.filter_mode]
	context.favorite_members = get_favorite_members(
		context.result_game.competition if context.result_game else None,
		frappe.session.user,
	)
	context.list_filters = get_list_filters(context.result_game, context.filter_mode)
	context.list_filter_options = get_list_filter_options(context.result_game)
	context.picks = get_result_picks(
		context.result_game,
		context.filter_mode,
		context.current_user_site,
		context.current_department,
		context.favorite_members,
		context.only_favorites,
		context.list_filters,
	)
	context.sort_by = get_sort_by()
	context.sort_order = get_sort_order()
	context.query_base = get_query_base(context)


def get_closed_games():
	return frappe.db.sql(
		'''
		select
			game.name,
			game.game_id,
			game.competition,
			game.team_a,
			game.team_b,
			game.start_time
		from `tabCompetition Game` game
		inner join `tabCompetition` competition on competition.name = game.competition
		where game.open = 0
			and game.do_not_show = 0
			and competition.open = 1
		order by cast(game.game_id as unsigned), game.game_id
		''',
		as_dict=True,
	)


def get_selected_game(games):
	game_names = {game.name for game in games}
	selected_game = frappe.form_dict.get('game')
	if selected_game in game_names:
		return selected_game
	if games:
		return games[0].name
	return ''


def get_result_game(game):
	if not game:
		return None

	result_game = frappe.db.sql(
		'''
		select
			game.name,
			game.game_id,
			game.competition,
			game.team_a,
			team_a.image as team_a_image,
			team_a.image_url as team_a_image_url,
			game.score_a,
			game.penalty_shootout_a,
			game.score_b,
			game.penalty_shootout_b,
			game.team_b,
			team_b.image as team_b_image,
			team_b.image_url as team_b_image_url,
			game.score_updated
		from `tabCompetition Game` game
		left join `tabCompetition Team` team_a on team_a.name = game.team_a
		left join `tabCompetition Team` team_b on team_b.name = game.team_b
		inner join `tabCompetition` competition on competition.name = game.competition
		where game.name = %(game)s
			and game.open = 0
			and game.do_not_show = 0
			and competition.open = 1
		limit 1
		''',
		{'game': game},
		as_dict=True,
	)
	if not result_game:
		return None

	result_game = result_game[0]
	result_game.team_a_image_src = get_team_image_src(result_game.team_a_image, result_game.team_a_image_url)
	result_game.team_b_image_src = get_team_image_src(result_game.team_b_image, result_game.team_b_image_url)
	result_game.has_penalty_shootout = result_game.penalty_shootout_a not in (None, '') and result_game.penalty_shootout_b not in (None, '')
	return result_game


def get_filter_mode():
	filter_mode = frappe.form_dict.get('filter') or FILTER_GENERAL
	if filter_mode in FACTOR_FIELDS:
		return filter_mode
	return FILTER_GENERAL


def get_sort_by():
	sort_by = frappe.form_dict.get('sort_by') or 'user'
	if sort_by in SORT_FIELDS:
		return sort_by
	return 'user'


def get_sort_order():
	return 'desc' if frappe.form_dict.get('sort_order') == 'desc' else 'asc'


def get_competition_pick_field(fieldname, fallback='total_points_cumulated'):
	if frappe.db.has_column('Competition Pick', fieldname):
		return fieldname
	return fallback


def get_current_departments(competition, user=None):
	user = user or frappe.session.user
	if not competition:
		return []

	return frappe.db.sql(
		'''
		select department.name, department.team
		from `tabFNSI User Department` user_department
		inner join `tabFNSI Department` department on department.name = user_department.department
		where user_department.user = %(user)s
			and user_department.status = 'Validated'
			and department.competition = %(competition)s
		order by department.team asc, department.name asc
		''',
		{'user': user, 'competition': competition},
		as_dict=True,
	)


def get_current_department(competition, departments=None):
	departments = departments if departments is not None else get_current_departments(competition)
	selected_department = frappe.form_dict.get('department')
	for department in departments:
		if department.name == selected_department:
			return department
	return departments[0] if departments else None


def get_list_filters(result_game=None, filter_mode=FILTER_GENERAL):
	if filter_mode != FILTER_GENERAL or not result_game:
		return frappe._dict({"country": "", "city": "", "department": ""})

	return frappe._dict(
		{
			"country": frappe.form_dict.get("country") or "",
			"city": frappe.form_dict.get("city") or "",
			"department": frappe.form_dict.get("list_department") or "",
		}
	)


def get_list_filter_options(result_game=None):
	options = frappe._dict({"countries": [], "cities": [], "departments": []})
	if not result_game:
		return options

	options.countries = frappe.db.sql_list(
		'''
		select distinct site.country
		from `tabCompetition Pick` pick
		inner join `tabUser` user on user.name = pick.user
		inner join `tabFNSI Site` site on site.name = user.location
		where pick.game = %(game)s
			and pick.not_played = 0
			and coalesce(site.country, '') != ''
		order by site.country asc
		''',
		{"game": result_game.name},
	)
	options.cities = frappe.db.sql_list(
		'''
		select distinct site.site
		from `tabCompetition Pick` pick
		inner join `tabUser` user on user.name = pick.user
		inner join `tabFNSI Site` site on site.name = user.location
		where pick.game = %(game)s
			and pick.not_played = 0
			and coalesce(site.site, '') != ''
		order by site.site asc
		''',
		{"game": result_game.name},
	)
	options.departments = frappe.db.sql(
		'''
		select distinct department.name, department.team
		from `tabCompetition Pick` pick
		inner join `tabFNSI User Department` user_department
			on user_department.user = pick.user
			and user_department.status = 'Validated'
		inner join `tabFNSI Department` department on department.name = user_department.department
		where pick.game = %(game)s
			and pick.not_played = 0
			and department.competition = %(competition)s
		order by department.team asc, department.name asc
		''',
		{"game": result_game.name, "competition": result_game.competition},
		as_dict=True,
	)
	return options


def get_favorite_name(competition, user):
	if not competition or not user:
		return ''
	return f'{competition} - {user}'


def get_favorite_members(competition, user):
	favorite_name = get_favorite_name(competition, user)
	if not favorite_name or not frappe.db.exists('FNSI Favorite', favorite_name):
		return set()

	return {
		row.member
		for row in frappe.get_all(
			'FNSI User List',
			filters={'parent': favorite_name, 'parenttype': 'FNSI Favorite', 'parentfield': 'favorites'},
			fields=['member'],
		)
		if row.member
	}


def get_result_picks(result_game, filter_mode, current_user_site, current_department, favorite_members, only_favorites, list_filters=None):
	if not result_game:
		return []

	factor_field = f"pick.{FACTOR_FIELDS.get(filter_mode, 'factor')}"
	total_points_field = f"pick.`{get_competition_pick_field(TOTAL_POINTS_FIELDS.get(filter_mode, 'total_points'), 'total_points')}`"
	total_points_cumulated_field = f"pick.`{get_competition_pick_field(TOTAL_POINTS_CUMULATED_FIELDS.get(filter_mode, 'total_points_cumulated'))}`"
	department_join = ''
	conditions = ["pick.game = %(game)s", "pick.not_played = 0"]
	params = {'game': result_game.name}

	if filter_mode == FILTER_SITE:
		if not current_user_site:
			return []
		conditions.append('user.location = %(user_site)s')
		params['user_site'] = current_user_site
	elif filter_mode == FILTER_DEPARTMENT:
		if not current_department:
			return []
		department_join = '''
		inner join `tabCompetition Department Ranking` department_ranking
			on department_ranking.game = pick.game
			and department_ranking.user = pick.user
			and department_ranking.department = %(department)s
		'''
		factor_field = 'department_ranking.factor'
		total_points_field = 'department_ranking.total_points'
		total_points_cumulated_field = 'department_ranking.total_points_cumulated'
		params['department'] = current_department.name

	list_filters = list_filters or frappe._dict()
	if filter_mode == FILTER_GENERAL:
		apply_general_list_filters(conditions, params, list_filters)

	if only_favorites:
		if not favorite_members:
			return []
		conditions.append('pick.user in %(favorite_members)s')
		params['favorite_members'] = tuple(favorite_members)

	sort_by = get_sort_by()
	sort_order = get_sort_order()
	sort_expression = SORT_FIELDS[sort_by].format(
		factor_field=factor_field,
		total_points_field=total_points_field,
		total_points_cumulated_field=total_points_cumulated_field,
	)
	order_by = f'{sort_expression} {sort_order}, user_full_name asc, pick.user asc'

	rows = frappe.db.sql(
		f'''
		select
			pick.name,
			pick.user,
			coalesce(nullif(user.full_name, ''), user.name) as user_full_name,
			pick.pick_a,
			pick.pick_b,
			pick.points,
			pick.exact_result,
			pick.good_difference,
			pick.good_trend,
			pick.coefficient,
			{factor_field} as factor,
			{total_points_field} as total_points,
			{total_points_cumulated_field} as total_points_cumulated
		from `tabCompetition Pick` pick
		inner join `tabUser` user on user.name = pick.user
		{department_join}
		where {' and '.join(conditions)}
		order by {order_by}
		''',
		params,
		as_dict=True,
	)

	for row in rows:
		row.is_favorite = row.user in favorite_members
		row.points_display = format_number(row.points, decimals=0)
		row.coefficient_display = format_number(row.coefficient, decimals=0)
		row.factor_display = format_number(row.factor, decimals=4)
		row.total_points_display = format_number(row.total_points, decimals=4)
		row.total_points_cumulated_display = format_number(row.total_points_cumulated, decimals=4)

	return rows


def apply_general_list_filters(conditions, params, list_filters):
	if list_filters.get("country") or list_filters.get("city"):
		conditions.append(
			'''exists (
				select 1
				from `tabFNSI Site` site
				where site.name = user.location
					and (%(country)s = '' or site.country = %(country)s)
					and (%(city)s = '' or site.site = %(city)s)
			)'''
		)
		params["country"] = list_filters.get("country") or ""
		params["city"] = list_filters.get("city") or ""
	if list_filters.get("department"):
		conditions.append(
			'''exists (
				select 1
				from `tabFNSI User Department` user_department
				where user_department.user = pick.user
					and user_department.department = %(list_department)s
					and user_department.status = 'Validated'
			)'''
		)
		params["list_department"] = list_filters.department


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


def get_team_image_src(image, image_url):
	return image or image_url or ''


def get_query_base(context):
	params = []
	if context.game:
		params.append('game=' + quote(context.game, safe=''))
	if context.filter_mode:
		params.append('filter=' + quote(context.filter_mode, safe=''))
	if context.filter_mode == FILTER_DEPARTMENT and getattr(context, 'current_department', None):
		params.append('department=' + quote(context.current_department.name, safe=''))
	if context.filter_mode == FILTER_GENERAL and getattr(context, 'list_filters', None):
		if context.list_filters.country:
			params.append('country=' + quote(context.list_filters.country, safe=''))
		if context.list_filters.city:
			params.append('city=' + quote(context.list_filters.city, safe=''))
		if context.list_filters.department:
			params.append('list_department=' + quote(context.list_filters.department, safe=''))
	if context.only_favorites:
		params.append('favorites=1')
	return '&'.join(params)


@frappe.whitelist()
def toggle_favorite_member(competition, member, is_favorite=None):
	require_user_location('/game_result')
	if not competition or not frappe.db.exists('Competition', competition):
		frappe.throw(_('Please select a valid competition.'))
	if not member or not frappe.db.exists('User', member):
		frappe.throw(_('Please select a valid user.'))

	favorite_name = get_favorite_name(competition, frappe.session.user)
	if frappe.db.exists('FNSI Favorite', favorite_name):
		favorite = frappe.get_doc('FNSI Favorite', favorite_name)
	else:
		favorite = frappe.get_doc(
			{
				'doctype': 'FNSI Favorite',
				'competition': competition,
				'user': frappe.session.user,
			}
		)

	existing = None
	for row in favorite.favorites:
		if row.member == member:
			existing = row
			break

	if is_favorite is None:
		should_be_favorite = existing is None
	else:
		should_be_favorite = frappe.utils.cint(is_favorite) == 1

	if should_be_favorite and not existing:
		favorite.append('favorites', {'member': member})
	elif not should_be_favorite and existing:
		favorite.remove(existing)

	if favorite.is_new():
		favorite.insert(ignore_permissions=True)
	else:
		favorite.save(ignore_permissions=True)
	frappe.db.commit()

	return {'member': member, 'is_favorite': should_be_favorite}
