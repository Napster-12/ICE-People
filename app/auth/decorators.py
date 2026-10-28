from functools import wraps

from flask import abort
from flask_login import current_user

from app.extensions import login_manager


def roles_required(*roles):
    """Require a signed-in user; with roles given, the user must hold at least one of them."""
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return login_manager.unauthorized()
            if roles and not current_user.has_role(*roles):
                abort(403)
            return view(*args, **kwargs)
        wrapped.roles_required = roles
        return wrapped
    return decorator
