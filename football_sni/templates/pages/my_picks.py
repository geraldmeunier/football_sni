from urllib.parse import quote

import frappe
from frappe import _

from frappe.utils import convert_utc_to_timezone, format_datetime, get_datetime

from football_sni.tasks import get_user_time_zone
from football_sni.website import add_user_settings_context, require_user_location


def get_context(context):
	require_user_location('/my_picks')
	add_user_settings_context(context)
	context.no_cache = 1
	context.show_sidebar = 0
	context.full_width = 1
	context.body_class = 'fsni-site'
	context.title = _('My Picks')
	context.user_time_zone = get_user_time_zone(frappe.session.user)
	context.pick_values = list(range(21))
	context.picks = get_my_picks(context.user_time_zone)


def get_my_picks(user_time_zone=None):
	user = frappe.session.user
	rows = frappe.db.sql(
		"""
		select
			cp.name,
			cp.competition,
			cp.game,
			cp.open,
			cp.pick_a,
			cp.pick_b,
			cg.game_id,
			cg.round,
			cg.start_time,
			cg.team_a,
			team_a.image as team_a_image,
			team_a.image_url as team_a_image_url,
			cg.team_b,
			team_b.image as team_b_image,
			team_b.image_url as team_b_image_url
		from `tabCompetition Pick` cp
		left join `tabCompetition Game` cg on cg.name = cp.game
		left join `tabCompetition Team` team_a on team_a.name = cg.team_a
		left join `tabCompetition Team` team_b on team_b.name = cg.team_b
		where cp.user = %(user)s
		order by cast(cg.game_id as unsigned), cg.game_id
		""",
		{'user': user},
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
		row.result_url = '/game_result?game=' + quote(row.game or '', safe='')

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
