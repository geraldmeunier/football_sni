# Copyright (c) 2026, Gerald Meunier and contributors
# For license information, please see license.txt

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import frappe
from frappe.utils import (
	add_to_date,
	cint,
	convert_utc_to_timezone,
	flt,
	format_datetime,
	get_datetime,
	get_system_timezone,
	get_url,
	now_datetime,
)

AVAILABLE_PICKS_TEMPLATE = "Available Picks"
PICK_REMINDER_TEMPLATE = "Pick Reminder"
SCORE_VALIDATION_RETRY_JOB_ID = "football_sni_validate_yesterday_competition_games_retry"


def all():
	create_new_subscription_picks()


def close_competition_games_before_start():
	cutoff = add_to_date(now_datetime(), hours=1)
	games = frappe.get_all(
		"Competition Game",
		filters={"open": 1, "start_time": ("<=", cutoff)},
		pluck="name",
	)

	for game in games:
		frappe.db.set_value("Competition Game", game, {"open": 0, "do_not_show": 0})
		frappe.db.sql(
			"""
			update `tabCompetition Pick`
			set not_played = 1
			where game = %(game)s
				and (
					pick_a is null
					or pick_a = ''
					or pick_a = 'null'
					or pick_b is null
					or pick_b = ''
					or pick_b = 'null'
				)
			""",
			{"game": game},
		)
		frappe.db.set_value("Competition Pick", {"game": game}, "open", 0)

	return len(games)


def validate_yesterday_competition_games(is_retry=False):
	games = get_unvalidated_yesterday_competition_games()
	if not games:
		return {"validated": 0, "pending_scores": 0}

	pending_games = [game for game in games if is_score_pending(game)]
	if pending_games:
		notify_site_admins_about_pending_scores(pending_games)
		schedule_competition_game_validation_retry()
		return {"validated": 0, "pending_scores": len(pending_games)}

	validated = 0
	for game in games:
		validate_competition_game(game)
		validated += 1

	return {"validated": validated, "pending_scores": 0}


def get_unvalidated_yesterday_competition_games():
	rows = frappe.db.sql(
		"""
		select
			cg.name,
			cg.competition,
			cg.round,
			cg.start_time,
			cg.score_a,
			cg.score_b,
			cg.score_updated,
			c.time_zone
		from `tabCompetition Game` cg
		inner join `tabCompetition` c on c.name = cg.competition
		where cg.validated = 0
			and cg.start_time is not null
		order by cg.start_time, cg.name
		""",
		as_dict=True,
	)

	games = []
	for game in rows:
		time_zone = get_competition_time_zone(game.time_zone)
		start_datetime = convert_utc_to_timezone(get_datetime(game.start_time), time_zone)
		yesterday = datetime.now(ZoneInfo(time_zone)).date() - timedelta(days=1)
		if start_datetime.date() == yesterday:
			game.time_zone = time_zone
			games.append(game)

	return games


def get_competition_time_zone(time_zone=None):
	time_zone = time_zone or get_system_timezone() or "Europe/Paris"
	try:
		ZoneInfo(time_zone)
	except ZoneInfoNotFoundError:
		return "Europe/Paris"
	return time_zone


def is_score_pending(game):
	return not cint(game.score_updated) or parse_score(game.score_a) is None or parse_score(game.score_b) is None


def validate_competition_game(game):
	score_a = parse_score(game.score_a)
	score_b = parse_score(game.score_b)
	coefficient = get_round_coefficient(game.competition, game.round)

	picks = frappe.get_all(
		"Competition Pick",
		filters={"game": game.name},
		fields=["name", "pick_a", "pick_b"],
	)
	for pick in picks:
		result = calculate_pick_result(pick.pick_a, pick.pick_b, score_a, score_b)
		frappe.db.set_value(
			"Competition Pick",
			pick.name,
			{
				"points": result["points"],
				"coefficient": coefficient,
				"exact_result": result["exact_result"],
				"good_difference": result["good_difference"],
				"good_trend": result["good_trend"],
				"no_play": result["did_play"],
				"not_played": 0 if result["did_play"] else 1,
			},
			update_modified=False,
		)

	update_game_factors(game.name)
	update_game_site_factors(game)
	update_game_department_factors(game)
	update_game_ranking_placeholder(game)

	frappe.db.set_value(
		"Competition Game",
		game.name,
		{"validated": 1},
		update_modified=False,
	)


def get_round_coefficient(competition, round_name):
	coefficient = frappe.db.get_value(
		"Competition Round List",
		{"parent": competition, "round": round_name},
		"coefficient",
	)
	return flt(coefficient) if coefficient is not None else 1


def calculate_pick_result(pick_a, pick_b, score_a, score_b):
	pick_a = parse_score(pick_a)
	pick_b = parse_score(pick_b)
	if pick_a is None or pick_b is None:
		return get_empty_pick_result(did_play=0)

	result = get_empty_pick_result(did_play=1)
	pick_difference = pick_a - pick_b
	score_difference = score_a - score_b

	if pick_a == score_a and pick_b == score_b:
		result["points"] = 4
		result["exact_result"] = 1
	elif score_a != score_b and pick_difference == score_difference:
		result["points"] = 2
		result["good_difference"] = 1
	elif score_a != score_b and sign(pick_difference) == sign(score_difference):
		result["points"] = 1
		result["good_trend"] = 1
	elif score_a == score_b and pick_a == pick_b:
		result["points"] = 1
		result["good_trend"] = 1

	return result


def get_empty_pick_result(did_play):
	return {
		"points": 0,
		"exact_result": 0,
		"good_difference": 0,
		"good_trend": 0,
		"did_play": did_play,
	}


def parse_score(value):
	if value is None or value == "":
		return None
	if isinstance(value, str) and value.strip().lower() in {"", "null", "none"}:
		return None
	try:
		return cint(value)
	except Exception:
		return None


def sign(value):
	if value > 0:
		return 1
	if value < 0:
		return -1
	return 0


def update_game_factors(game):
	aggregate = get_pick_factor_aggregate("cp.game = %(game)s", {"game": game})
	frappe.db.sql(
		"""
		update `tabCompetition Pick`
		set factor = %(factor)s,
			total_points = coalesce(cast(points as decimal(18,6)), 0)
				* coalesce(cast(coefficient as decimal(18,6)), 0)
				* %(factor)s
		where game = %(game)s
		""",
		{"game": game, "factor": aggregate["factor"]},
	)


def update_game_site_factors(game):
	frappe.db.sql(
		"""
		update `tabCompetition Pick`
		set factor_site = 0,
			total_points_site = 0
		where game = %(game)s
		""",
		{"game": game.name},
	)

	for site in frappe.get_all("FNSI Site", pluck="name"):
		aggregate = get_pick_factor_aggregate(
			"cp.game = %(game)s and user.location = %(site)s",
			{"game": game.name, "site": site},
			join_user=True,
		)
		frappe.db.sql(
			"""
			update `tabCompetition Pick` cp
			inner join `tabUser` user on user.name = cp.user
			set cp.factor_site = %(factor)s,
				cp.total_points_site = coalesce(cast(cp.points as decimal(18,6)), 0)
					* coalesce(cast(cp.coefficient as decimal(18,6)), 0)
					* %(factor)s
			where cp.game = %(game)s
				and user.location = %(site)s
			""",
			{"game": game.name, "site": site, "factor": aggregate["factor"]},
		)


def update_game_department_factors(game):
	frappe.db.sql(
		"""
		update `tabCompetition Pick`
		set factor_department = 0,
			total_points_department = 0
		where game = %(game)s
		""",
		{"game": game.name},
	)
	frappe.db.delete("Competition Department Ranking", {"game": game.name})

	departments = frappe.get_all(
		"FNSI Department",
		filters={"competition": game.competition},
		pluck="name",
	)
	for department in departments:
		department_filter = """
			cp.game = %(game)s
			and exists (
				select 1
				from `tabFNSI User Department` fud
				where fud.user = cp.user
					and fud.department = %(department)s
					and fud.status = 'Validated'
			)
		"""
		aggregate = get_pick_factor_aggregate(
			department_filter,
			{"game": game.name, "department": department},
		)
		frappe.db.sql(
			"""
			update `tabCompetition Pick` cp
			set cp.factor_department = %(factor)s,
				cp.total_points_department = coalesce(cast(cp.points as decimal(18,6)), 0)
					* coalesce(cast(cp.coefficient as decimal(18,6)), 0)
					* %(factor)s
			where cp.game = %(game)s
				and exists (
					select 1
					from `tabFNSI User Department` fud
					where fud.user = cp.user
						and fud.department = %(department)s
						and fud.status = 'Validated'
				)
			""",
			{"game": game.name, "department": department, "factor": aggregate["factor"]},
		)
		users = frappe.db.sql(
			"""
			select cp.user, cp.points, cp.coefficient
			from `tabCompetition Pick` cp
			where cp.game = %(game)s
				and exists (
					select 1
					from `tabFNSI User Department` fud
					where fud.user = cp.user
						and fud.department = %(department)s
						and fud.status = 'Validated'
				)
			""",
			{"game": game.name, "department": department},
			as_dict=True,
		)
		for row in users:
			frappe.get_doc(
				{
					"doctype": "Competition Department Ranking",
					"competition": game.competition,
					"game": game.name,
					"department": department,
					"user": row.user,
					"factor": aggregate["factor"],
					"total_points": flt(row.points) * flt(row.coefficient) * aggregate["factor"],
				}
			).insert(ignore_permissions=True)


def get_pick_factor_aggregate(where_clause, params, join_user=False):
	user_join = "inner join `tabUser` user on user.name = cp.user" if join_user else ""
	row = frappe.db.sql(
		f"""
		select
			coalesce(sum(cp.exact_result), 0) as exact_results,
			coalesce(sum(cp.good_difference), 0) as good_differences,
			coalesce(sum(cp.good_trend), 0) as good_trends,
			coalesce(sum(cp.no_play), 0) as did_play
		from `tabCompetition Pick` cp
		{user_join}
		where {where_clause}
		""",
		params,
		as_dict=True,
	)[0]

	number_good_trends = cint(row.exact_results) + cint(row.good_differences) + cint(row.good_trends)
	number_players = cint(row.did_play)
	return {
		"factor": get_factor(number_good_trends, number_players),
		"total_points": number_good_trends,
	}


def get_factor(number_good_trends, number_players):
	if number_players != 1:
		factor = 1 + round(1 - ((number_good_trends - 1) / (number_players - 1)), 3)
	else:
		factor = 0
	if number_good_trends == 0:
		factor = 0
	return factor


def update_game_ranking_placeholder(game):
	game = get_ranking_game(game)
	if not game:
		return {"rankings": 0}

	update_game_cumulated_points(game)
	prior_rankings = get_prior_rankings(game)
	ranking_maps = get_game_ranking_maps(game)
	department_prior_rankings = get_prior_department_rankings(game)
	department_ranking_maps = get_department_rankings(game)
	update_department_ranking_rows(game, department_ranking_maps, department_prior_rankings)
	legacy_department_rankings = get_legacy_department_ranking_map(department_ranking_maps)

	frappe.db.delete("Competition Ranking", {"game": game.name})
	created = 0
	for pick in get_game_ranking_picks(game.name):
		frappe.get_doc(
			{
				"doctype": "Competition Ranking",
				"competition": game.competition,
				"game": game.name,
				"user": pick.user,
				"date": get_datetime(game.start_time).date() if game.start_time else None,
				"prior_ranking": prior_rankings["ranking"].get(pick.user, 0),
				"prior_ranking_site": prior_rankings["ranking_site"].get(pick.user, 0),
				"prior_ranking_department": prior_rankings["ranking_department"].get(pick.user, 0),
				"ranking": ranking_maps["ranking"].get(pick.user, 0),
				"ranking_site": ranking_maps["ranking_site"].get(pick.user, 0),
				"ranking_department": legacy_department_rankings.get(pick.user, 0),
			}
		).insert(ignore_permissions=True)
		created += 1

	return {"rankings": created}


def get_ranking_game(game):
	game_name = game.name if hasattr(game, "name") else game
	if not game_name:
		return None

	game_doc = frappe.db.get_value(
		"Competition Game",
		game_name,
		["name", "competition", "start_time"],
		as_dict=True,
	)
	return game_doc


def update_game_cumulated_points(game):
	update_game_cumulated_points_for_scope(
		game,
		"`total_points_cumulated`",
		"factor",
	)
	update_game_cumulated_points_for_scope(
		game,
		"total_points_site_cumulated",
		"factor_site",
	)
	update_game_cumulated_points_for_scope(
		game,
		"total_points_department_cumulated",
		"factor_department",
	)
	update_game_department_cumulated_points(game)


def update_game_cumulated_points_for_scope(game, cumulative_field, factor_field):
	frappe.db.sql(
		f"""
		update `tabCompetition Pick` current_pick
		set current_pick.{cumulative_field} = (
			select coalesce(sum(
				coalesce(cast(pick.points as decimal(18,6)), 0)
				* coalesce(cast(pick.coefficient as decimal(18,6)), 0)
				* coalesce(cast(pick.{factor_field} as decimal(18,6)), 0)
			), 0)
			from `tabCompetition Pick` pick
			inner join `tabCompetition Game` pick_game on pick_game.name = pick.game
			where pick.competition = %(competition)s
				and pick.user = current_pick.user
				and pick.not_played = 0
				and (
					pick.game = %(game)s
					or (
						pick_game.validated = 1
						and (
							pick_game.start_time < %(start_time)s
							or %(start_time)s is null
						)
					)
				)
		)
		where current_pick.game = %(game)s
		""",
		{
			"competition": game.competition,
			"game": game.name,
			"start_time": game.start_time,
		},
	)


def update_game_department_cumulated_points(game):
	frappe.db.sql(
		"""
		update `tabCompetition Department Ranking` current_ranking
		set current_ranking.total_points_cumulated = (
			select coalesce(sum(
				coalesce(cast(pick.points as decimal(18,6)), 0)
				* coalesce(cast(pick.coefficient as decimal(18,6)), 0)
				* coalesce(cast(department_ranking.factor as decimal(18,6)), 0)
			), 0)
			from `tabCompetition Department Ranking` department_ranking
			inner join `tabCompetition Pick` pick
				on pick.game = department_ranking.game
				and pick.user = department_ranking.user
			inner join `tabCompetition Game` pick_game on pick_game.name = pick.game
			where department_ranking.competition = %(competition)s
				and department_ranking.department = current_ranking.department
				and department_ranking.user = current_ranking.user
				and pick.not_played = 0
				and (
					pick.game = %(game)s
					or (
						pick_game.validated = 1
						and (
							pick_game.start_time < %(start_time)s
							or %(start_time)s is null
						)
					)
				)
		)
		where current_ranking.game = %(game)s
		""",
		{
			"competition": game.competition,
			"game": game.name,
			"start_time": game.start_time,
		},
	)


def get_prior_rankings(game):
	prior_rankings = {
		"ranking": {},
		"ranking_site": {},
		"ranking_department": {},
	}
	previous_game = get_previous_ranking_game(game)
	if not previous_game:
		return prior_rankings

	rows = frappe.get_all(
		"Competition Ranking",
		filters={"competition": game.competition, "game": previous_game},
		fields=["user", "ranking", "ranking_site", "ranking_department"],
	)
	for row in rows:
		prior_rankings["ranking"][row.user] = cint(row.ranking)
		prior_rankings["ranking_site"][row.user] = cint(row.ranking_site)
		prior_rankings["ranking_department"][row.user] = cint(row.ranking_department)

	return prior_rankings


def get_prior_department_rankings(game):
	previous_game = get_previous_ranking_game(game)
	if not previous_game:
		return {}

	rows = frappe.get_all(
		"Competition Department Ranking",
		filters={"competition": game.competition, "game": previous_game},
		fields=["department", "user", "ranking"],
	)
	return {(row.department, row.user): cint(row.ranking) for row in rows}


def get_previous_ranking_game(game):
	if not game.start_time:
		return None

	rows = frappe.db.sql(
		"""
		select game.name
		from `tabCompetition Game` game
		where game.competition = %(competition)s
			and game.validated = 1
			and game.start_time < %(start_time)s
			and exists (
				select 1
				from `tabCompetition Ranking` ranking
				where ranking.game = game.name
			)
		order by game.start_time desc, game.name desc
		limit 1
		""",
		{"competition": game.competition, "start_time": game.start_time},
		as_dict=True,
	)
	return rows[0].name if rows else None


def get_game_ranking_picks(game):
	return frappe.db.sql(
		"""
		select pick.user
		from `tabCompetition Pick` pick
		inner join `tabUser` user on user.name = pick.user
		where pick.game = %(game)s
		order by coalesce(nullif(user.full_name, ''), user.name), pick.user
		""",
		{"game": game},
		as_dict=True,
	)


def get_game_ranking_maps(game):
	return {
		"ranking": get_rankings_by_query(
			"""
			select
				pick.user,
				coalesce(cast(pick.`total_points_cumulated` as decimal(18,6)), 0) as score,
				coalesce(nullif(user.full_name, ''), user.name) as user_full_name
			from `tabCompetition Pick` pick
			inner join `tabUser` user on user.name = pick.user
			where pick.game = %(game)s
			""",
			{"game": game.name},
		),
		"ranking_site": get_site_rankings(game),
		"ranking_department": {},
	}


def get_site_rankings(game):
	rankings = {}
	sites = frappe.db.sql_list(
		"""
		select distinct user.location
		from `tabCompetition Pick` pick
		inner join `tabUser` user on user.name = pick.user
		where pick.game = %(game)s
			and coalesce(user.location, '') != ''
		order by user.location
		""",
		{"game": game.name},
	)
	for site in sites:
		rankings.update(
			get_rankings_by_query(
				"""
				select
					pick.user,
					coalesce(cast(pick.total_points_site_cumulated as decimal(18,6)), 0) as score,
					coalesce(nullif(user.full_name, ''), user.name) as user_full_name
				from `tabCompetition Pick` pick
				inner join `tabUser` user on user.name = pick.user
				where pick.game = %(game)s
					and user.location = %(site)s
				""",
				{"game": game.name, "site": site},
			)
		)
	return rankings


def get_department_rankings(game):
	rankings = {}
	departments = frappe.get_all(
		"FNSI Department",
		filters={"competition": game.competition},
		pluck="name",
	)
	for department in departments:
		for user, ranking in get_rankings_by_query(
			"""
			select
				department_ranking.user,
				coalesce(cast(department_ranking.total_points_cumulated as decimal(18,6)), 0) as score,
				coalesce(nullif(user.full_name, ''), user.name) as user_full_name
			from `tabCompetition Department Ranking` department_ranking
			inner join `tabUser` user on user.name = department_ranking.user
			where department_ranking.game = %(game)s
				and department_ranking.department = %(department)s
			""",
			{"game": game.name, "department": department},
		).items():
			rankings[(department, user)] = ranking
	return rankings


def update_department_ranking_rows(game, ranking_maps, prior_rankings):
	for (department, user), ranking in ranking_maps.items():
		frappe.db.set_value(
			"Competition Department Ranking",
			f"{department} - {game.name} - {user}",
			{
				"prior_ranking": prior_rankings.get((department, user), 0),
				"ranking": ranking,
			},
			update_modified=False,
		)


def get_legacy_department_ranking_map(ranking_maps):
	rankings = {}
	for (department, user), ranking in sorted(ranking_maps.items()):
		rankings.setdefault(user, ranking)
	return rankings


def get_rankings_by_query(query, params):
	rows = frappe.db.sql(
		f"""
		{query}
		order by score desc, user_full_name asc, user asc
		""",
		params,
		as_dict=True,
	)
	return {row.user: index for index, row in enumerate(rows, start=1)}


def notify_site_admins_about_pending_scores(games):
	recipients = get_site_administrator_recipients()
	if not recipients:
		return

	lines = []
	for game in games:
		lines.append(
			f"<li><strong>{frappe.utils.escape_html(game.name)}</strong> "
			f"({frappe.utils.escape_html(game.competition)}, {frappe.utils.escape_html(game.round or '')})</li>"
		)

	frappe.sendmail(
		recipients=recipients,
		subject="Football SNI - scores still pending",
		message=(
			"<p>The daily competition validation could not run because some games from yesterday "
			"do not have updated scores yet.</p>"
			f"<ul>{''.join(lines)}</ul>"
			"<p>The validation job has been scheduled again in 30 minutes.</p>"
		),
		delayed=False,
	)


def get_site_administrator_recipients():
	users = frappe.get_all(
		"Has Role",
		filters={"role": "System Manager", "parenttype": "User"},
		pluck="parent",
	)
	recipients = []
	for user in users:
		user_row = frappe.db.get_value("User", user, ["email", "enabled"])
		if not user_row:
			continue
		email, enabled = user_row
		if enabled and email:
			recipients.append(email)
	return sorted(set(recipients))


def schedule_competition_game_validation_retry():
	from frappe.utils.background_jobs import get_queue

	queue = get_queue("short")
	queue.enqueue_in(
		timedelta(minutes=30),
		"frappe.utils.background_jobs.execute_job",
		site=frappe.local.site,
		user=frappe.session.user,
		method="football_sni.tasks.validate_yesterday_competition_games",
		event=None,
		job_name="football_sni.tasks.validate_yesterday_competition_games",
		kwargs={"is_retry": True},
		is_async=True,
		job_id=SCORE_VALIDATION_RETRY_JOB_ID,
	)


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


def send_daily_pick_reminders():
	for user in get_users_with_incomplete_open_picks():
		frappe.enqueue(send_pick_reminder_to_input, user=user)


def get_users_with_incomplete_open_picks():
	return frappe.db.sql_list(
		"""
		select distinct cp.user
		from `tabCompetition Pick` cp
		inner join `tabUser` user on user.name = cp.user
		where cp.open = 1
			and user.enabled = 1
			and (
				cp.pick_a is null
				or cp.pick_a = ''
				or cp.pick_a = 'null'
				or cp.pick_b is null
				or cp.pick_b = ''
				or cp.pick_b = 'null'
			)
		order by cp.user
		"""
	)


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


def send_pick_reminder_to_input(user):
	picks = get_available_picks(user)
	if not picks:
		return

	recipient = frappe.db.get_value("User", user, "email") or user
	if not recipient:
		return

	template = ensure_pick_reminder_email_template()
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
		template = frappe.get_doc({"doctype": "Email Template", "__newname": AVAILABLE_PICKS_TEMPLATE})

	template.subject = "Your picks are ready - time to make the call!"
	template.use_html = 1
	template.response_html = AVAILABLE_PICKS_EMAIL_HTML

	if template.is_new():
		template.insert(ignore_permissions=True)
	else:
		template.save(ignore_permissions=True)

	return template


def ensure_pick_reminder_email_template():
	if frappe.db.exists("Email Template", PICK_REMINDER_TEMPLATE):
		template = frappe.get_doc("Email Template", PICK_REMINDER_TEMPLATE)
	else:
		template = frappe.get_doc({"doctype": "Email Template", "__newname": PICK_REMINDER_TEMPLATE})

	template.subject = "Tiny nudge: your picks are still waiting"
	template.use_html = 1
	template.response_html = PICK_REMINDER_EMAIL_HTML

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


PICK_REMINDER_EMAIL_HTML = """
<div style="background: #f6f8fb; color: #162033; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; padding: 24px;">
	<div style="background: #ffffff; border: 1px solid #dde3ea; border-radius: 8px; box-shadow: 0 10px 28px rgba(22, 32, 51, 0.08); overflow: hidden;">
		<div style="background: #0f766e; color: #ffffff; padding: 18px 22px;">
			<div style="font-size: 12px; font-weight: 700; letter-spacing: 0; text-transform: uppercase;">{{ app_name }}</div>
			<div style="font-size: 24px; font-weight: 800; line-height: 1.15; margin-top: 4px;">Your picks need you</div>
		</div>

		<div style="padding: 22px;">
			<p style="font-size: 16px; margin: 0 0 10px;">Hey {{ user }},</p>
			<p style="color: #526171; font-size: 14px; line-height: 1.55; margin: 0 0 16px;">A few open picks are still waiting for your genius. Give them a score, trust the instinct, and let the leaderboard drama begin.</p>

			<p style="margin: 0 0 22px;">
				<a href="{{ my_picks_url }}" style="background: #0f766e; border-radius: 8px; color: #ffffff; display: inline-block; font-weight: 700; padding: 10px 14px; text-decoration: none;">Complete My Picks</a>
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

			<p style="color: #697789; font-size: 13px; line-height: 1.55; margin: 18px 0 0;">No pressure... except, well, the very official business of proving your football instincts are elite. Have fun!</p>
		</div>
	</div>
</div>
"""
