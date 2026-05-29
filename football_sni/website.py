from urllib.parse import quote

import frappe
from frappe import _


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
	context.update(get_competition_cards())


@frappe.whitelist()
def subscribe_to_competition(competition):
	require_login("/home")

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
