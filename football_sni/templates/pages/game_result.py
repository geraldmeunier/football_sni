from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils import flt, get_url

from football_sni.website import add_user_settings_context, get_current_user_location, require_user_location


FILTER_GENERAL = 'general'
FILTER_SITE = 'site'
FILTER_DEPARTMENT = 'department'


FACTOR_FIELDS = {
	FILTER_GENERAL: 'factor',
	FILTER_SITE: 'factor_site',
	FILTER_DEPARTMENT: 'factor_department',
}


SORT_FIELDS = {
	'user': 'user_full_name',
	'pick_a': 'cast(pick.pick_a as signed)',
	'pick_b': 'cast(pick.pick_b as signed)',
	'points': 'cast(pick.points as decimal(18,6))',
	'coefficient': 'cast(pick.coefficient as decimal(18,6))',
	'factor': 'cast({factor_field} as decimal(18,6))',
	'total_points': 'total_points',
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
	context.current_department = get_current_department(context.result_game.competition if context.result_game else None)
	if context.filter_mode == FILTER_DEPARTMENT and not context.current_department:
		context.filter_mode = FILTER_GENERAL
	context.favorite_members = get_favorite_members(
		context.result_game.competition if context.result_game else None,
		frappe.session.user,
	)
	context.picks = get_result_picks(
		context.result_game,
		context.filter_mode,
		context.current_user_site,
		context.current_department,
		context.favorite_members,
		context.only_favorites,
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


def get_current_department(competition):
	if not competition:
		return None

	departments = frappe.db.sql(
		'''
		select department.name, department.team
		from `tabFNSI User Department` user_department
		inner join `tabFNSI Department` department on department.name = user_department.department
		where user_department.user = %(user)s
			and user_department.status = 'Validated'
			and department.competition = %(competition)s
		order by department.team asc, department.name asc
		limit 1
		''',
		{'user': frappe.session.user, 'competition': competition},
		as_dict=True,
	)
	return departments[0] if departments else None


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


def get_result_picks(result_game, filter_mode, current_user_site, current_department, favorite_members, only_favorites):
	if not result_game:
		return []

	factor_field = FACTOR_FIELDS.get(filter_mode, 'factor')
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
		conditions.append(
			'''
			exists (
				select 1
				from `tabFNSI User Department` user_department
				where user_department.user = pick.user
					and user_department.department = %(department)s
					and user_department.status = 'Validated'
			)
			'''
		)
		params['department'] = current_department.name

	if only_favorites:
		if not favorite_members:
			return []
		conditions.append('pick.user in %(favorite_members)s')
		params['favorite_members'] = tuple(favorite_members)

	sort_by = get_sort_by()
	sort_order = get_sort_order()
	sort_expression = SORT_FIELDS[sort_by].format(factor_field=f'pick.{factor_field}')
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
			pick.coefficient,
			pick.{factor_field} as factor,
			(
				coalesce(cast(pick.points as decimal(18,6)), 0)
				* coalesce(cast(pick.coefficient as decimal(18,6)), 0)
				* coalesce(cast(pick.{factor_field} as decimal(18,6)), 0)
			) as total_points
		from `tabCompetition Pick` pick
		inner join `tabUser` user on user.name = pick.user
		where {' and '.join(conditions)}
		order by {order_by}
		''',
		params,
		as_dict=True,
	)

	for row in rows:
		row.is_favorite = row.user in favorite_members
		row.total_points_display = format_number(row.total_points)

	return rows


def format_number(value):
	if value in (None, ''):
		return ''
	value = flt(value)
	if value == int(value):
		return str(int(value))
	return f'{value:.2f}'.rstrip('0').rstrip('.')


def get_team_image_src(image, image_url):
	image_src = image or image_url
	if not image_src:
		return ''
	if image_src.startswith(('http://', 'https://')):
		return image_src
	return get_url(image_src)


def get_query_base(context):
	params = []
	if context.game:
		params.append('game=' + quote(context.game, safe=''))
	if context.filter_mode:
		params.append('filter=' + quote(context.filter_mode, safe=''))
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
