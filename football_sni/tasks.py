# Copyright (c) 2026, Gerald Meunier and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import convert_utc_to_timezone, format_datetime, get_datetime, get_system_timezone, get_url

AVAILABLE_PICKS_TEMPLATE = "Available Picks"


def all():
	create_new_subscription_picks()


def create_new_subscription_picks():
	subscriptions = frappe.get_all(
		"Competition Subscription",
		filters={"new_subscription": 1},
		fields=["name", "competition", "user"],
	)

	for subscription in subscriptions:
		games = frappe.get_all(
			"Competition Game",
			filters={"competition": subscription.competition, "open": 1},
			pluck="name",
		)

		created_picks = 0
		for game in games:
			if frappe.db.exists(
				"Competition Pick",
				{
					"competition": subscription.competition,
					"user": subscription.user,
					"game": game,
				},
			):
				continue

			frappe.get_doc(
				{
					"doctype": "Competition Pick",
					"competition": subscription.competition,
					"user": subscription.user,
					"game": game,
					"open": 1,
				}
			).insert(ignore_permissions=True)
			created_picks += 1

		frappe.db.set_value(
			"Competition Subscription",
			subscription.name,
			"new_subscription",
			0,
			update_modified=False,
		)

		if created_picks:
			frappe.enqueue(alert_new_picks_to_input, user=subscription.user)


def get_website_app_name():
	return frappe.db.get_single_value("Website Settings", "app_name") or "Football SNI"


def alert_new_picks_to_input(user):
	picks = get_available_picks(user)
	if not picks:
		return

	recipient = frappe.db.get_value("User", user, "email") or user
	if not recipient:
		return

	template = ensure_available_picks_email_template()
	context = {
		"user": user,
		"picks": picks,
		"my_picks_url": get_url("/my_picks"),
		"app_name": get_website_app_name(),
	}
	email = template.get_formatted_email(context)

	frappe.sendmail(
		recipients=[recipient],
		subject=email["subject"],
		message=email["message"],
		reference_doctype="User",
		reference_name=user,
	)


def get_available_picks(user):
	picks = frappe.db.sql(
		"""
		select
			cp.name,
			cp.competition,
			cp.game,
			cg.game_id,
			cg.round,
			cg.start_time,
			cg.team_a,
			team_a.image as team_a_image,
			team_a.image_url as team_a_image_url,
			cg.team_b,
			team_b.image as team_b_image,
			team_b.image_url as team_b_image_url,
			cp.pick_a,
			cp.pick_b
		from `tabCompetition Pick` cp
		left join `tabCompetition Game` cg on cg.name = cp.game
		left join `tabCompetition Team` team_a on team_a.name = cg.team_a
		left join `tabCompetition Team` team_b on team_b.name = cg.team_b
		where cp.user = %(user)s
			and cp.open = 1
			and (
				cp.pick_a is null
				or cp.pick_a = ''
				or cp.pick_a = 'null'
				or cp.pick_b is null
				or cp.pick_b = ''
				or cp.pick_b = 'null'
			)
		order by cg.start_time, cg.game_id
		""",
		{"user": user},
		as_dict=True,
	)

	user_time_zone = get_user_time_zone(user)
	for pick in picks:
		pick.start_date = get_user_start_date(pick.start_time, user_time_zone)
		pick.team_a_image_src = get_team_image_src(pick.team_a_image, pick.team_a_image_url)
		pick.team_b_image_src = get_team_image_src(pick.team_b_image, pick.team_b_image_url)

	return picks


def get_user_time_zone(user):
	return frappe.db.get_value("User", user, "time_zone") or get_system_timezone()


def get_user_start_date(start_time, time_zone, include_time_zone=True):
	if not start_time:
		return ""

	start_datetime = get_datetime(start_time)
	start_datetime = convert_utc_to_timezone(start_datetime, time_zone)
	start_date = format_datetime(start_datetime, 'yyyy-MM-dd HH:mm')
	if include_time_zone:
		return f"{start_date} ({time_zone})"
	return start_date


def ensure_competition_team_images_are_public():
	files = frappe.get_all(
		"File",
		filters={
			"attached_to_doctype": "Competition Team",
			"attached_to_field": "image",
		},
		fields=["name", "is_private"],
	)

	updated = 0
	for file in files:
		if file.is_private:
			frappe.db.set_value("File", file.name, "is_private", 0, update_modified=False)
			updated += 1

	return updated


def get_team_image_src(image, image_url):
	image_src = image or image_url
	if not image_src:
		return ""

	if image_src.startswith(("http://", "https://")):
		return image_src

	return get_url(image_src)


def ensure_available_picks_email_template():
	if frappe.db.exists("Email Template", AVAILABLE_PICKS_TEMPLATE):
		template = frappe.get_doc("Email Template", AVAILABLE_PICKS_TEMPLATE)
	else:
		template = frappe.get_doc({"doctype": "Email Template", "name": AVAILABLE_PICKS_TEMPLATE})

	template.subject = "Your picks are ready - time to make the call!"
	template.use_html = 1
	template.response_html = AVAILABLE_PICKS_EMAIL_HTML

	if template.is_new():
		template.insert(ignore_permissions=True)
	else:
		template.save(ignore_permissions=True)

	return template


AVAILABLE_PICKS_EMAIL_HTML = """
<div style="background: #f6f8fb; color: #162033; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; padding: 24px;">
	<div style="background: #ffffff; border: 1px solid #dde3ea; border-radius: 8px; box-shadow: 0 10px 28px rgba(22, 32, 51, 0.08); overflow: hidden;">
		<div style="background: #0f766e; color: #ffffff; padding: 18px 22px;">
			<div style="font-size: 12px; font-weight: 700; letter-spacing: 0; text-transform: uppercase;">{{ app_name }}</div>
			<div style="font-size: 24px; font-weight: 800; line-height: 1.15; margin-top: 4px;">Your picks are ready</div>
		</div>

		<div style="padding: 22px;">
			<p style="font-size: 16px; margin: 0 0 10px;">Hey {{ user }},</p>
			<p style="color: #526171; font-size: 14px; line-height: 1.55; margin: 0 0 16px;">Your next set of picks is waiting. The pitch is fresh, the matchups are ready, and now it is your turn to bring the magic.</p>

			<p style="margin: 0 0 22px;">
				<a href="{{ my_picks_url }}" style="background: #0f766e; border-radius: 8px; color: #ffffff; display: inline-block; font-weight: 700; padding: 10px 14px; text-decoration: none;">Open My Picks</a>
			</p>

			<table cellpadding="0" cellspacing="0" style="border-collapse: collapse; width: 100%;">
				<thead>
					<tr>
						<th align="left" style="background: #e8f4f2; border-bottom: 1px solid #c7d1dc; color: #0f766e; font-size: 12px; padding: 10px 8px; text-transform: uppercase;">Game ID</th>
						<th align="left" style="background: #e8f4f2; border-bottom: 1px solid #c7d1dc; color: #0f766e; font-size: 12px; padding: 10px 8px; text-transform: uppercase;">Round</th>
						<th align="left" style="background: #e8f4f2; border-bottom: 1px solid #c7d1dc; color: #0f766e; font-size: 12px; padding: 10px 8px; text-transform: uppercase;">Date</th>
						<th align="center" colspan="5" style="background: #e8f4f2; border-bottom: 1px solid #c7d1dc; color: #0f766e; font-size: 12px; padding: 10px 8px; text-transform: uppercase;">Game</th>
					</tr>
				</thead>
				<tbody>
					{% for pick in picks %}
					<tr>
						<td style="border-bottom: 1px solid #dde3ea; color: #162033; font-weight: 700; padding: 10px 8px;">{{ pick.game_id or "" }}</td>
						<td style="border-bottom: 1px solid #dde3ea; color: #526171; padding: 10px 8px;">{{ pick.round or "" }}</td>
						<td style="border-bottom: 1px solid #dde3ea; color: #526171; padding: 10px 8px; white-space: nowrap;">{{ pick.start_date or "" }}</td>
						<td align="right" style="border-bottom: 1px solid #dde3ea; color: #162033; font-weight: 700; padding: 10px 6px;">{{ pick.team_a or "" }}</td>
						<td align="center" style="border-bottom: 1px solid #dde3ea; padding: 10px 4px; width: 34px;">
							{% if pick.team_a_image_src %}
							<img src="{{ pick.team_a_image_src }}" alt="{{ pick.team_a or '' }}" style="height: 20px; max-width: 32px; vertical-align: middle;" />
							{% endif %}
						</td>
						<td align="center" style="border-bottom: 1px solid #dde3ea; color: #697789; font-weight: 800; padding: 10px 2px; width: 12px;">:</td>
						<td align="center" style="border-bottom: 1px solid #dde3ea; padding: 10px 4px; width: 34px;">
							{% if pick.team_b_image_src %}
							<img src="{{ pick.team_b_image_src }}" alt="{{ pick.team_b or '' }}" style="height: 20px; max-width: 32px; vertical-align: middle;" />
							{% endif %}
						</td>
						<td align="left" style="border-bottom: 1px solid #dde3ea; color: #162033; font-weight: 700; padding: 10px 6px;">{{ pick.team_b or "" }}</td>
					</tr>
					{% endfor %}
				</tbody>
			</table>

			<p style="color: #697789; font-size: 13px; line-height: 1.55; margin: 18px 0 0;">No pressure... except, well, eternal leaderboard glory. Have fun!</p>
		</div>
	</div>
</div>
"""
