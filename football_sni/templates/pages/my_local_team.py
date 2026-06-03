import frappe
from frappe import _
from frappe.utils import get_email_address, get_url, validate_email_address
from markupsafe import escape

from football_sni.tasks import get_website_app_name
from football_sni.website import add_user_settings_context, require_user_location

TEAM_JOIN_REQUEST_TEMPLATE = "Local Team Join Request"
TEAM_JOIN_ACCEPTED_TEMPLATE = "Local Team Join Accepted"
TEAM_JOIN_REJECTED_TEMPLATE = "Local Team Join Rejected"
TEAM_MEMBER_REMOVED_TEMPLATE = "Local Team Member Removed"


def get_context(context):
	require_user_location('/my_local_team')
	add_user_settings_context(context)
	context.no_cache = 1
	context.show_sidebar = 0
	context.full_width = 1
	context.body_class = 'fsni-site'
	context.title = _('My Local Team')
	context.open_competitions = get_open_competitions()
	context.selected_competition = get_selected_competition(context.open_competitions)
	context.current_departments = get_current_departments(context.selected_competition)
	context.global_owned_department = get_owned_department()
	context.owned_department = get_owned_department(context.selected_competition)
	context.has_department = bool(context.current_departments)
	context.can_create_team = bool(
		context.selected_competition
		and not context.global_owned_department
	)
	context.departments = get_departments(context.selected_competition)
	context.pending_members = get_department_members(context.owned_department, 'Asked')
	context.validated_members = get_department_members(context.owned_department, 'Validated')


def get_open_competitions():
	return frappe.get_all(
		'Competition',
		filters={'open': 1},
		fields=['name', 'title'],
		order_by='modified desc',
	)


def get_selected_competition(open_competitions):
	open_competition_names = {competition.name for competition in open_competitions}
	selected_competition = frappe.form_dict.get('competition')
	if selected_competition in open_competition_names:
		return selected_competition
	if open_competitions:
		return open_competitions[0].name
	return ''


def get_current_departments(competition=None, user=None):
	user = user or frappe.session.user
	if not competition:
		return set()

	return {
		row.department
		for row in frappe.db.sql(
			'''
			select user_department.department
			from `tabFNSI User Department` user_department
			inner join `tabFNSI Department` department
				on department.name = user_department.department
			where user_department.user = %(user)s
				and department.competition = %(competition)s
			''',
			{'user': user, 'competition': competition},
			as_dict=True,
		)
	}


def get_owned_department(competition=None, user=None):
	user = user or frappe.session.user
	filters = {'department_owner': user}
	if competition:
		filters['competition'] = competition

	return frappe.db.get_value(
		'FNSI Department',
		filters,
		['name', 'competition', 'team', 'department_owner'],
		as_dict=True,
	)


def get_departments(competition):
	if not competition:
		return []

	return frappe.db.sql(
		'''
		select
			department.name,
			department.team,
			department.department_owner,
			coalesce(nullif(user.full_name, ''), user.name) as department_owner_full_name
		from `tabFNSI Department` department
		left join `tabUser` user
			on user.name = department.department_owner
		where department.competition = %(competition)s
		order by department.team asc
		''',
		{'competition': competition},
		as_dict=True,
	)


def get_department_members(department, status):
	if not department:
		return []

	return frappe.db.sql(
		'''
		select
			user_department.name,
			user_department.user,
			coalesce(nullif(user.full_name, ''), user.name) as user_full_name
		from `tabFNSI User Department` user_department
		inner join `tabUser` user
			on user.name = user_department.user
		where user_department.department = %(department)s
			and user_department.status = %(status)s
			and user_department.user != %(owner)s
		order by user.full_name asc, user.name asc
		''',
		{
			'department': department.name,
			'owner': department.department_owner,
			'status': status,
		},
		as_dict=True,
	)


def validate_open_competition(competition):
	if not frappe.db.exists('Competition', {'name': competition, 'open': 1}):
		frappe.throw(_('Please select a valid open competition.'))
	return competition


def validate_open_department(department):
	department_doc = frappe.db.get_value(
		'FNSI Department',
		department,
		['name', 'competition', 'department_owner'],
		as_dict=True,
	)
	if not department_doc:
		frappe.throw(_('Please select a valid team.'))

	validate_open_competition(department_doc.competition)
	return department_doc


def validate_team_name(team):
	team = (team or '').strip()
	if not team:
		frappe.throw(_('Please enter a team name.'))
	return team


@frappe.whitelist()
def create_own_department(competition, team):
	require_user_location('/my_local_team')
	competition = validate_open_competition(competition)
	team = validate_team_name(team)

	if get_owned_department():
		frappe.throw(_('You already own a local team.'))

	if frappe.db.exists('FNSI Department', {'competition': competition, 'team': team}):
		frappe.throw(_('This team already exists for the selected competition.'))

	department_doc = frappe.get_doc(
		{
			'doctype': 'FNSI Department',
			'competition': competition,
			'team': team,
			'department_owner': frappe.session.user,
		}
	)
	department_doc.insert(ignore_permissions=True)

	user_department_doc = frappe.get_doc(
		{
			'doctype': 'FNSI User Department',
			'department': department_doc.name,
			'user': frappe.session.user,
			'status': 'Validated',
		}
	)
	user_department_doc.insert(ignore_permissions=True)
	frappe.db.commit()

	return {'department': department_doc.name}


@frappe.whitelist()
def delete_owned_department(department):
	require_user_location('/my_local_team')
	department_doc = validate_open_department(department)
	if department_doc.department_owner != frappe.session.user:
		frappe.throw(_('You can only delete your own local team.'))

	memberships = frappe.get_all(
		'FNSI User Department',
		filters={'department': department},
		pluck='name',
	)
	for membership in memberships:
		frappe.delete_doc('FNSI User Department', membership, ignore_permissions=True)

	frappe.delete_doc('FNSI Department', department, ignore_permissions=True)
	frappe.db.commit()

	return {'department': department}


@frappe.whitelist()
def join_department(department):
	require_user_location('/my_local_team')
	department_doc = validate_open_department(department)

	if frappe.db.exists('FNSI User Department', {'department': department, 'user': frappe.session.user}):
		frappe.throw(_('You already have a request or membership for this local team.'))

	doc = frappe.get_doc(
		{
			'doctype': 'FNSI User Department',
			'department': department,
			'user': frappe.session.user,
			'status': 'Asked',
		}
	)
	doc.insert(ignore_permissions=True)
	requester_name = get_user_display_name(frappe.session.user)
	department_name = department_doc.team or department_doc.name
	send_team_mail(
		department_doc.department_owner,
		TEAM_JOIN_REQUEST_TEMPLATE,
		{
			"requester_name": requester_name,
			"team_name": department_name,
		},
	)
	frappe.db.commit()

	return {'department': department}


@frappe.whitelist()
def leave_department(department):
	require_user_location('/my_local_team')
	department_doc = validate_open_department(department)
	if department_doc.department_owner == frappe.session.user:
		frappe.throw(_('Use Delete to remove a local team you own.'))

	membership = frappe.db.exists(
		'FNSI User Department',
		{'department': department, 'user': frappe.session.user},
	)
	if not membership:
		frappe.throw(_('You do not belong to this local team.'))

	frappe.delete_doc('FNSI User Department', membership, ignore_permissions=True)
	frappe.db.commit()

	return {'department': department}


def get_owned_membership(membership):
	membership_doc = frappe.db.get_value(
		'FNSI User Department',
		membership,
		['name', 'department', 'user', 'status'],
		as_dict=True,
	)
	if not membership_doc:
		frappe.throw(_('Please select a valid team member.'))

	department_doc = frappe.db.get_value(
		'FNSI Department',
		membership_doc.department,
		['name', 'team', 'department_owner'],
		as_dict=True,
	)
	if not department_doc or department_doc.department_owner != frappe.session.user:
		frappe.throw(_('You can only manage members of your own local team.'))

	return membership_doc, department_doc


def get_user_display_name(user):
	return frappe.db.get_value('User', user, 'full_name') or user


def send_team_mail(user, template_name, context):
	recipient = validate_email_address(get_email_address(user) or user)
	if not recipient:
		return

	template = ensure_team_email_template(template_name)
	context = frappe._dict({
		k: escape(v) if isinstance(v, str) else v
		for k, v in (context or {}).items()
	})
	context.update(
		{
			"app_name": escape(get_website_app_name()),
			"my_local_team_url": get_url("/my_local_team"),
			"recipient_name": escape(get_user_display_name(user)),
		}
	)
	email = template.get_formatted_email(context)

	frappe.sendmail(
		recipients=[recipient],
		subject=email["subject"],
		message=email["message"],
		reference_doctype="User",
		reference_name=user,
	)


def ensure_team_email_template(template_name):
	if template_name not in TEAM_EMAIL_TEMPLATES:
		frappe.throw(_("Unknown local team email template."))

	definition = TEAM_EMAIL_TEMPLATES[template_name]
	if frappe.db.exists("Email Template", template_name):
		template = frappe.get_doc("Email Template", template_name)
	else:
		template = frappe.get_doc({"doctype": "Email Template", "__newname": template_name})

	template.subject = definition["subject"]
	template.use_html = 1
	template.response_html = definition["html"]

	if template.is_new():
		template.insert(ignore_permissions=True)
	else:
		template.save(ignore_permissions=True)

	return template


@frappe.whitelist()
def validate_member(membership):
	require_user_location('/my_local_team')
	membership_doc, department_doc = get_owned_membership(membership)
	if membership_doc.status != 'Asked':
		frappe.throw(_('Only asked memberships can be validated.'))

	frappe.db.set_value('FNSI User Department', membership_doc.name, 'status', 'Validated')
	send_team_mail(
		membership_doc.user,
		TEAM_JOIN_ACCEPTED_TEMPLATE,
		{
			"team_name": department_doc.team,
			"owner_name": get_user_display_name(department_doc.department_owner),
		},
	)
	frappe.db.commit()

	return {'membership': membership_doc.name}


@frappe.whitelist()
def reject_member(membership):
	require_user_location('/my_local_team')
	membership_doc, department_doc = get_owned_membership(membership)
	if membership_doc.status != 'Asked':
		frappe.throw(_('Only asked memberships can be rejected.'))

	owner_name = get_user_display_name(department_doc.department_owner)
	frappe.db.set_value('FNSI User Department', membership_doc.name, 'status', 'Rejected')
	send_team_mail(
		membership_doc.user,
		TEAM_JOIN_REJECTED_TEMPLATE,
		{
			"team_name": department_doc.team,
			"owner_name": owner_name,
		},
	)
	frappe.delete_doc('FNSI User Department', membership_doc.name, ignore_permissions=True)
	frappe.db.commit()

	return {'membership': membership_doc.name}


@frappe.whitelist()
def remove_member(membership):
	require_user_location('/my_local_team')
	membership_doc, department_doc = get_owned_membership(membership)
	if membership_doc.status != 'Validated':
		frappe.throw(_('Only validated members can be removed.'))

	send_team_mail(
		membership_doc.user,
		TEAM_MEMBER_REMOVED_TEMPLATE,
		{
			"team_name": department_doc.team,
			"owner_name": get_user_display_name(department_doc.department_owner),
		},
	)
	frappe.delete_doc('FNSI User Department', membership_doc.name, ignore_permissions=True)
	frappe.db.commit()

	return {'membership': membership_doc.name}


TEAM_EMAIL_TEMPLATES = {
	TEAM_JOIN_REQUEST_TEMPLATE: {
		"subject": "{{ requester_name }} wants to join {{ team_name }}",
		"html": """
<div style="background: #f6f8fb; color: #162033; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; padding: 24px;">
	<div style="background: #ffffff; border: 1px solid #dde3ea; border-radius: 8px; box-shadow: 0 10px 28px rgba(22, 32, 51, 0.08); overflow: hidden;">
		<div style="background: #0f766e; color: #ffffff; padding: 18px 22px;">
			<div style="font-size: 12px; font-weight: 700; text-transform: uppercase;">{{ app_name }}</div>
			<div style="font-size: 24px; font-weight: 800; line-height: 1.15; margin-top: 4px;">New teammate at the door</div>
		</div>
		<div style="padding: 22px;">
			<p style="font-size: 16px; margin: 0 0 10px;">Hi {{ recipient_name }},</p>
			<p style="color: #526171; font-size: 14px; line-height: 1.55; margin: 0 0 16px;">Good news! <strong>{{ requester_name }}</strong> would like to join your team <strong>{{ team_name }}</strong>.</p>
			<p style="color: #526171; font-size: 14px; line-height: 1.55; margin: 0 0 22px;">Head over to My Local Team to validate or reject the request and keep your squad list match-ready.</p>
			<p style="margin: 0 0 18px;"><a href="{{ my_local_team_url }}" style="background: #0f766e; border-radius: 8px; color: #ffffff; display: inline-block; font-weight: 700; padding: 10px 14px; text-decoration: none;">Review the request</a></p>
			<p style="color: #697789; font-size: 13px; line-height: 1.55; margin: 0;">Or copy this link into your browser:<br><a href="{{ my_local_team_url }}" style="color: #0f766e;">{{ my_local_team_url }}</a></p>
		</div>
	</div>
</div>
""",
	},
	TEAM_JOIN_ACCEPTED_TEMPLATE: {
		"subject": "You are in: {{ team_name }}",
		"html": """
<div style="background: #f6f8fb; color: #162033; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; padding: 24px;">
	<div style="background: #ffffff; border: 1px solid #dde3ea; border-radius: 8px; box-shadow: 0 10px 28px rgba(22, 32, 51, 0.08); overflow: hidden;">
		<div style="background: #0f766e; color: #ffffff; padding: 18px 22px;"><div style="font-size: 12px; font-weight: 700; text-transform: uppercase;">{{ app_name }}</div><div style="font-size: 24px; font-weight: 800; line-height: 1.15; margin-top: 4px;">Welcome to the squad</div></div>
		<div style="padding: 22px;">
			<p style="font-size: 16px; margin: 0 0 10px;">Hi {{ recipient_name }},</p>
			<p style="color: #526171; font-size: 14px; line-height: 1.55; margin: 0 0 16px;">Great news! Your request has been accepted and you have joined <strong>{{ team_name }}</strong>.</p>
			<p style="color: #526171; font-size: 14px; line-height: 1.55; margin: 0 0 22px;">Warm up, meet the crew, and get ready to play.</p>
			<p style="margin: 0 0 18px;"><a href="{{ my_local_team_url }}" style="background: #0f766e; border-radius: 8px; color: #ffffff; display: inline-block; font-weight: 700; padding: 10px 14px; text-decoration: none;">Open My Local Team</a></p>
			<p style="color: #697789; font-size: 13px; line-height: 1.55; margin: 0;">Link: <a href="{{ my_local_team_url }}" style="color: #0f766e;">{{ my_local_team_url }}</a></p>
		</div>
	</div>
</div>
""",
	},
	TEAM_JOIN_REJECTED_TEMPLATE: {
		"subject": "Update on your request for {{ team_name }}",
		"html": """
<div style="background: #f6f8fb; color: #162033; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; padding: 24px;">
	<div style="background: #ffffff; border: 1px solid #dde3ea; border-radius: 8px; box-shadow: 0 10px 28px rgba(22, 32, 51, 0.08); overflow: hidden;">
		<div style="background: #334155; color: #ffffff; padding: 18px 22px;"><div style="font-size: 12px; font-weight: 700; text-transform: uppercase;">{{ app_name }}</div><div style="font-size: 24px; font-weight: 800; line-height: 1.15; margin-top: 4px;">Team request update</div></div>
		<div style="padding: 22px;">
			<p style="font-size: 16px; margin: 0 0 10px;">Hi {{ recipient_name }},</p>
			<p style="color: #526171; font-size: 14px; line-height: 1.55; margin: 0 0 16px;">{{ owner_name }} has declined your request to join <strong>{{ team_name }}</strong>.</p>
			<p style="color: #526171; font-size: 14px; line-height: 1.55; margin: 0 0 22px;">Maybe it was not the team you meant to pick. No worries, have another look and choose the right squad.</p>
			<p style="margin: 0 0 18px;"><a href="{{ my_local_team_url }}" style="background: #0f766e; border-radius: 8px; color: #ffffff; display: inline-block; font-weight: 700; padding: 10px 14px; text-decoration: none;">Browse teams</a></p>
			<p style="color: #697789; font-size: 13px; line-height: 1.55; margin: 0;">Link: <a href="{{ my_local_team_url }}" style="color: #0f766e;">{{ my_local_team_url }}</a></p>
		</div>
	</div>
</div>
""",
	},
	TEAM_MEMBER_REMOVED_TEMPLATE: {
		"subject": "Team update: {{ team_name }}",
		"html": """
<div style="background: #f6f8fb; color: #162033; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; padding: 24px;">
	<div style="background: #ffffff; border: 1px solid #dde3ea; border-radius: 8px; box-shadow: 0 10px 28px rgba(22, 32, 51, 0.08); overflow: hidden;">
		<div style="background: #334155; color: #ffffff; padding: 18px 22px;"><div style="font-size: 12px; font-weight: 700; text-transform: uppercase;">{{ app_name }}</div><div style="font-size: 24px; font-weight: 800; line-height: 1.15; margin-top: 4px;">Line-up update</div></div>
		<div style="padding: 22px;">
			<p style="font-size: 16px; margin: 0 0 10px;">Hi {{ recipient_name }},</p>
			<p style="color: #526171; font-size: 14px; line-height: 1.55; margin: 0 0 16px;">You have been removed from <strong>{{ team_name }}</strong>.</p>
			<p style="color: #526171; font-size: 14px; line-height: 1.55; margin: 0 0 22px;">Thanks for being part of the adventure, and keep an eye out for the next line-up.</p>
			<p style="margin: 0 0 18px;"><a href="{{ my_local_team_url }}" style="background: #0f766e; border-radius: 8px; color: #ffffff; display: inline-block; font-weight: 700; padding: 10px 14px; text-decoration: none;">Open My Local Team</a></p>
			<p style="color: #697789; font-size: 13px; line-height: 1.55; margin: 0;">Link: <a href="{{ my_local_team_url }}" style="color: #0f766e;">{{ my_local_team_url }}</a></p>
		</div>
	</div>
</div>
""",
	},
}
