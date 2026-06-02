from urllib.parse import quote

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import cint, get_system_timezone
from frappe.utils.html_utils import sanitize_html
from frappe.utils.momentjs import get_all_timezones
from markupsafe import Markup


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


def get_user_site_doctype():
	if frappe.db.exists("DocType", "FNSI Site"):
		return "FNSI Site"
	return "FNSI User Site"


def is_valid_user_location(user_site):
	return bool(user_site) and frappe.db.exists(get_user_site_doctype(), user_site)


def get_current_user_location(user=None):
	user = user or frappe.session.user
	if user == "Guest":
		return ""

	user_site = frappe.db.get_value("User", user, "location") or ""
	if is_valid_user_location(user_site):
		return user_site
	return ""


def get_current_user_rgpd_consent(user=None):
	user = user or frappe.session.user
	if user == "Guest" or not frappe.db.has_column("User", "fsni_rgpd_consent"):
		return False
	return bool(frappe.db.get_value("User", user, "fsni_rgpd_consent"))


def has_user_access(user=None):
	return bool(get_current_user_location(user) and get_current_user_rgpd_consent(user))


def add_user_settings_context(context):
	context.time_zones = get_all_timezones()
	user_fields = ["time_zone", "location"]
	if frappe.db.has_column("User", "fsni_rgpd_consent"):
		user_fields.append("fsni_rgpd_consent")
	user_settings = frappe.db.get_value(
		"User",
		frappe.session.user,
		user_fields,
		as_dict=True,
	) or {}
	context.current_time_zone = user_settings.get("time_zone") or get_system_timezone()
	context.current_user_site = get_current_user_location()
	context.fsni_rgpd_consent = bool(user_settings.get("fsni_rgpd_consent"))
	context.fsni_rgpd_text = get_rgpd_text()
	context.has_user_location = bool(context.current_user_site)
	context.has_user_access = bool(context.has_user_location and context.fsni_rgpd_consent)
	context.user_sites = frappe.get_all(
		get_user_site_doctype(),
		fields=["name", "country", "site"],
		order_by="country asc, site asc",
	)
	context.countries = [
		row.name
		for row in frappe.get_all(
			"Country",
			fields=["name"],
			order_by="name asc",
		)
	]


def get_rgpd_text():
	text = frappe.db.get_single_value("FSNI Settings", "rgpd") or ""
	return Markup(sanitize_html(text, always_sanitize=True))


def require_user_location(redirect_to="/home"):
	require_login(redirect_to)
	if has_user_access():
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
		"redirect_to": "/home",
		"message": _("Thanks! An email will be sent as soon as your space is created."),
	}


@frappe.whitelist()
def update_competition_pick(pick, pick_a=None, pick_b=None):
	require_user_location('/my_picks')

	doc = frappe.get_doc('Competition Pick', pick)
	if doc.user != frappe.session.user:
		frappe.throw(_('You can only update your own picks.'), frappe.PermissionError)

	game_open = frappe.db.get_value('Competition Game', doc.game, 'open')
	if cint(doc.open) != 1 or cint(game_open) != 1:
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
def update_user_settings(time_zone, user_site=None, rgpd_consent=None):
	require_login('/home')

	if time_zone not in get_all_timezones():
		frappe.throw(_('Please select a valid time zone.'))

	user_site = user_site or ''
	if user_site and not frappe.db.exists(get_user_site_doctype(), user_site):
		frappe.throw(_('Please select a valid FSNI Site.'))

	user = frappe.get_doc('User', frappe.session.user)
	user.time_zone = time_zone
	user.location = user_site
	if frappe.db.has_column("User", "fsni_rgpd_consent") and rgpd_consent is not None:
		user.fsni_rgpd_consent = frappe.utils.cint(rgpd_consent)
	user.save(ignore_permissions=True)
	frappe.db.commit()

	return {
		'time_zone': user.time_zone,
		'user_site': user.location,
		'rgpd_consent': bool(getattr(user, "fsni_rgpd_consent", 0)),
	}


@frappe.whitelist()
@rate_limit(limit=10, seconds=3600)
def create_user_site(country, site):
	require_login('/home')

	country = (country or '').strip()
	site = (site or '').strip()
	if not country:
		frappe.throw(_('Please select a country.'))
	if not site:
		frappe.throw(_('Please enter a city.'))
	if len(site) > 100:
		frappe.throw(_('City name must not exceed 100 characters.'))
	if not frappe.db.exists('Country', country):
		frappe.throw(_('Please select a valid country.'))

	user_site_doctype = get_user_site_doctype()
	user_site_name = f'{country} / {site}'
	if not frappe.db.exists(user_site_doctype, user_site_name):
		doc = frappe.get_doc(
			{
				'doctype': user_site_doctype,
				'country': country,
				'site': site,
			}
		)
		doc.insert(ignore_permissions=True)
	else:
		doc = frappe.get_doc(user_site_doctype, user_site_name)

	user = frappe.get_doc('User', frappe.session.user)
	user.location = doc.name
	user.save(ignore_permissions=True)
	frappe.db.commit()

	return {
		'user_site': doc.name,
		'country': doc.country,
		'site': doc.site,
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
