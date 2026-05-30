import re

import frappe
from frappe import _
from frappe.core.doctype.user.user import sign_up as frappe_sign_up
from frappe.utils import validate_email_address


def get_allowed_signup_domains():
    settings = frappe.get_single("FSNI Settings")
    return {
        row.domain.strip().lower()
        for row in settings.domains
        if row.domain and row.domain.strip()
    }


def get_name_from_email(email):
    local_part = email.split("@", 1)[0]
    parts = [part for part in re.split(r"[._-]+", local_part) if part]

    if not parts:
        return "", "", ""

    first_name = parts[0].capitalize()
    last_name = " ".join(part.capitalize() for part in parts[1:])
    full_name = " ".join(part for part in (first_name, last_name) if part)

    return first_name, last_name, full_name


@frappe.whitelist(allow_guest=True)
def sign_up(email, full_name, redirect_to=None):
    email = (email or "").strip().lower()
    validate_email_address(email, throw=True)

    domain = email.rsplit("@", 1)[-1]
    if domain not in get_allowed_signup_domains():
        frappe.throw(
            _("Please sign up with an approved email domain."),
            title=_("Not Allowed"),
        )

    first_name, last_name, email_full_name = get_name_from_email(email)
    result = frappe_sign_up(email, email_full_name or full_name, redirect_to)

    if frappe.db.exists("User", email):
        frappe.db.set_value(
            "User",
            email,
            {
                "first_name": first_name,
                "last_name": last_name,
                "full_name": email_full_name or full_name,
            },
            update_modified=False,
        )

    return result
