import requests

import frappe
from frappe import _
from frappe.utils.html_utils import sanitize_html
from markupsafe import Markup
from frappe.utils.password import get_decrypted_password


TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
DEFAULT_LOGIN_MESSAGE = (
	"<strong>Friendly locker-room reminder:</strong> choose a unique password for this site.<br>"
	"Your professional Windows password stays on its own team and does not play this match."
)


def _get_settings_password(fieldname):
	value = get_decrypted_password("FSNI Settings", "FSNI Settings", fieldname, raise_exception=False)
	if value:
		return value

	return frappe.db.get_single_value("FSNI Settings", fieldname)


def get_turnstile_site_key():
	return _get_settings_password("turnstile_site_key")


def get_turnstile_secret_key():
	return _get_settings_password("turnstile_secret_key")


def get_login_message():
	message = frappe.db.get_single_value("FSNI Settings", "login_message") or DEFAULT_LOGIN_MESSAGE
	return Markup(sanitize_html(message, always_sanitize=True))


@frappe.whitelist(allow_guest=True)
def get_login_security_context():
	site_key = get_turnstile_site_key()

	return {
		"turnstile_enabled": bool(site_key and get_turnstile_secret_key()),
		"turnstile_site_key": site_key,
		"login_message": get_login_message(),
	}


def validate_turnstile_token(token=None):
	secret_key = get_turnstile_secret_key()
	site_key = get_turnstile_site_key()

	if not secret_key and not site_key:
		return

	if not secret_key or not site_key:
		frappe.throw(
			_("Cloudflare Turnstile is not fully configured."),
			title=_("Login Protection"),
		)

	token = token or frappe.form_dict.get("cf_turnstile_response") or frappe.form_dict.get(
		"cf-turnstile-response"
	)
	if not token:
		frappe.throw(_("Please complete the security check."), title=_("Login Protection"))

	try:
		response = requests.post(
			TURNSTILE_VERIFY_URL,
			data={
				"secret": secret_key,
				"response": token,
				"remoteip": getattr(frappe.local, "request_ip", None),
			},
			timeout=10,
		)
		result = response.json()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Turnstile verification failed")
		frappe.throw(
			_("Unable to verify the security check. Please try again."),
			title=_("Login Protection"),
		)

	if not result.get("success"):
		frappe.throw(_("Security check failed. Please try again."), title=_("Login Protection"))


def validate_turnstile_for_login(login_manager=None):
	validate_turnstile_token()
