from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils import get_system_timezone
from frappe.utils.momentjs import get_all_timezones


def get_website_user_home_page(user):
	if user == "Guest":
		return "login"
	return "home"


def require_login(redirect_to=None):
	if frappe.session.user != "Guest":
		return

	target = quote(redirect_to or frappe.local.request.path or "/home")
	frappe.local.flags.redirect_location = f"/login?redirect-to={target}"
	raise frappe.Redirect


def get_current_user_location(user=None):
	user = user or frappe.session.user
	if user == "Guest":
		return ""
	return frappe.db.get_value("User", user, "location") or ""


def get_user_site_doctype():
	if frappe.db.exists("DocType", "FNSI Site"):
		return "FNSI Site"
	return "FNSI User Site"


def add_user_settings_context(context):
	context.time_zones = get_all_timezones()
	user_settings = frappe.db.get_value(
		"User",
		frappe.session.user,
		["time_zone", "location"],
		as_dict=True,
	) or {}
	context.current_time_zone = user_settings.get("time_zone") or get_system_timezone()
	context.current_user_site = user_settings.get("location") or ""
	context.has_user_location = bool(context.current_user_site)
	context.user_sites = frappe.get_all(
		get_user_site_doctype(),
		fields=["name", "country", "site"],
		order_by="country asc, site asc",
	)


def require_user_location(redirect_to="/home"):
	require_login(redirect_to)
	if get_current_user_location():
		return

	frappe.local.flags.redirect_location = "/home"
	raise frappe.Redirect


def get_competition_cards(user=None):
	user = user or frappe.session.user
	competitions = frappe.get_all(
		"Competition",
		fields=["name", "title", "open", "image"],
		order_by="modified desc",
	)
	subscriptions = {
		row.competition: row
		for row in frappe.get_all(
			"Competition Subscription",
			filters={"user": user},
			fields=["name", "competition", "new_subscription", "stop_subscription"],
		)
	}

	open_subscribed = []
	open_available = []
	past = []

	for competition in competitions:
		card = {
			"name": competition.name,
			"title": competition.title or competition.name,
			"image": competition.image,
			"url_name": quote(competition.name, safe=""),
			"subscription": subscriptions.get(competition.name),
		}

		if competition.open:
			if subscriptions.get(competition.name) and not subscriptions[competition.name].stop_subscription:
				open_subscribed.append(card)
			else:
				open_available.append(card)
		else:
			past.append(card)

	return {
		"open_subscribed": open_subscribed,
		"open_available": open_available,
		"past": past,
	}


def get_context(context):
	require_login("/home")
	context.no_cache = 1
	context.show_sidebar = 0
	context.full_width = 1
	context.body_class = "fsni-site"
	context.title = _("Home")
	add_user_settings_context(context)
	context.update(get_competition_cards())


@frappe.whitelist()
def subscribe_to_competition(competition):
	require_user_location("/home")

	if not frappe.db.exists("Competition", {"name": competition, "open": 1}):
		frappe.throw(_("This competition is not open for subscription."))

	existing = frappe.db.exists(
		"Competition Subscription",
		{"user": frappe.session.user, "competition": competition},
	)

	if existing:
		doc = frappe.get_doc("Competition Subscription", existing)
		doc.new_subscription = 1
		doc.stop_subscription = 0
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc(
			{
				"doctype": "Competition Subscription",
				"user": frappe.session.user,
				"competition": competition,
				"new_subscription": 1,
			}
		)
		doc.insert(ignore_permissions=True)

	frappe.db.commit()
	return {
		"competition": competition,
		"redirect_to": "/my_competition?competition=" + quote(competition, safe=""),
		"message": _("Thanks! An email will be sent as soon as your space is created."),
	}


@frappe.whitelist()
def update_competition_pick(pick, pick_a=None, pick_b=None):
	require_user_location('/my_picks')

	doc = frappe.get_doc('Competition Pick', pick)
	if doc.user != frappe.session.user:
		frappe.throw(_('You can only update your own picks.'), frappe.PermissionError)

	if not doc.open:
		frappe.throw(_('This pick is closed and can no longer be modified.'))

	doc.pick_a = validate_pick_value(pick_a, _('Pick A'))
	doc.pick_b = validate_pick_value(pick_b, _('Pick B'))
	doc.save(ignore_permissions=True)
	frappe.db.commit()

	return {
		'name': doc.name,
		'pick_a': doc.pick_a,
		'pick_b': doc.pick_b,
	}


@frappe.whitelist()
def update_user_settings(time_zone, user_site=None):
	require_login('/home')

	if time_zone not in get_all_timezones():
		frappe.throw(_('Please select a valid time zone.'))

	user_site = user_site or ''
	if user_site and not frappe.db.exists(get_user_site_doctype(), user_site):
		frappe.throw(_('Please select a valid FSNI Site.'))

	user = frappe.get_doc('User', frappe.session.user)
	user.time_zone = time_zone
	user.location = user_site
	user.save(ignore_permissions=True)
	frappe.db.commit()

	return {
		'time_zone': user.time_zone,
		'user_site': user.location,
	}


@frappe.whitelist()
def update_user_time_zone(time_zone):
	return update_user_settings(time_zone, get_current_user_location())


def validate_pick_value(value, label):
	if value in (None, ''):
		return ''

	try:
		value = int(value)
	except (TypeError, ValueError):
		frappe.throw(_('{0} must be an integer.').format(label))

	if value < 0 or value > 20:
		frappe.throw(_('{0} must be between 0 and 20.').format(label))

	return str(value)
