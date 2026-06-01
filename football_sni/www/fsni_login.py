import frappe
from frappe.www.login import get_context as frappe_login_get_context

from football_sni.security import get_login_security_context


no_cache = True


def get_context(context):
	frappe_login_get_context(context)
	context.for_test = "fsni_login.html"
	context.fsni_login_security = frappe._dict(get_login_security_context())
	return context
