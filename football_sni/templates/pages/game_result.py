import frappe
from frappe import _

from football_sni.website import add_user_settings_context, require_user_location


def get_context(context):
	require_user_location('/game_result')
	add_user_settings_context(context)
	context.no_cache = 1
	context.show_sidebar = 0
	context.full_width = 1
	context.body_class = 'fsni-site'
	context.title = _('Game Result')
	context.game = frappe.form_dict.get('game')

	if context.game and not frappe.db.exists('Competition Pick', {'user': frappe.session.user, 'game': context.game}):
		frappe.local.flags.redirect_location = '/my_picks'
		raise frappe.Redirect
