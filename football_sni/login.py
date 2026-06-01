import frappe
from frappe.rate_limiter import rate_limit
from frappe.www.login import (
	get_login_with_email_link_ratelimit,
	send_login_link as frappe_send_login_link,
)

from football_sni.security import validate_turnstile_token


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=get_login_with_email_link_ratelimit, seconds=60 * 60)
def send_login_link(email: str, cf_turnstile_response: str | None = None):
	validate_turnstile_token(cf_turnstile_response)
	return frappe_send_login_link(email)
