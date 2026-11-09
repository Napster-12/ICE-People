"""Which portal (HR admin, manager or staff self-service) the signed-in user is in. Everyone is staff, so everyone
can use the staff portal; users with more than one portal switch between them from the sidebar (1 Nov 2026)."""
from flask import session
from flask_login import current_user

PORTAL_LABELS = {"admin": "HR admin portal", "manager": "Manager portal", "staff": "Staff portal"}


def current_portal(user=None):
    """The portal chosen at sign-in or with the switcher, if the user may use it; otherwise their main one."""
    user = user or current_user
    chosen = session.get("portal")
    return chosen if chosen in user.portals else user.landing
