import frappe
from frappe import _
from frappe.utils import get_email_address, validate_email_address

from football_sni.website import add_user_settings_context, require_user_location


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
	context.owned_department = get_owned_department(context.selected_competition)
	context.has_department = bool(context.current_departments)
	context.can_create_team = bool(
		context.selected_competition
		and not context.current_departments
		and not context.owned_department
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
	if not competition:
		return None

	return frappe.db.get_value(
		'FNSI Department',
		{'competition': competition, 'department_owner': user},
		['name', 'team', 'department_owner'],
		as_dict=True,
	)


def get_departments(competition):
	if not competition:
		return []

	return frappe.get_all(
		'FNSI Department',
		filters={'competition': competition},
		fields=['name', 'team', 'department_owner'],
		order_by='team asc',
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

	if get_current_departments(competition):
		frappe.throw(_('You already belong to a local team for this competition.'))

	if get_owned_department(competition):
		frappe.throw(_('You already own a local team for this competition.'))

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

	if get_current_departments(department_doc.competition):
		frappe.throw(_('You already belong to a local team for this competition.'))

	if get_owned_department(department_doc.competition):
		frappe.throw(_('You already own a local team for this competition.'))

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
		_('{0} wants to join {1}').format(requester_name, department_name),
		_('Good news!\n\n{0} would like to join your team {1}.\nHead over to My Local Team to validate or reject the request.').format(requester_name, department_name),
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


def send_team_mail(user, subject, message):
	recipient = validate_email_address(get_email_address(user) or user)
	if not recipient:
		return

	frappe.sendmail(
		recipients=[recipient],
		subject=subject,
		message=message,
	)


@frappe.whitelist()
def validate_member(membership):
	require_user_location('/my_local_team')
	membership_doc, department_doc = get_owned_membership(membership)
	if membership_doc.status != 'Asked':
		frappe.throw(_('Only asked memberships can be validated.'))

	frappe.db.set_value('FNSI User Department', membership_doc.name, 'status', 'Validated')
	send_team_mail(
		membership_doc.user,
		_('Welcome to {0}!').format(department_doc.team),
		_('Great news! Your request has been accepted and you have joined {0}. Warm up, meet the crew, and get ready to play!').format(department_doc.team),
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
		_('About your request for {0}').format(department_doc.team),
		_('{0} has declined your request to join {1}. Maybe it was not the team you meant to pick?\nNo worries, have another look and choose the right squad!').format(owner_name, department_doc.team),
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
		_('You have left {0}').format(department_doc.team),
		_('Team update: you have been removed from {0}. Thanks for being part of the adventure, and keep an eye out for the next line-up!').format(department_doc.team),
	)
	frappe.delete_doc('FNSI User Department', membership_doc.name, ignore_permissions=True)
	frappe.db.commit()

	return {'membership': membership_doc.name}
