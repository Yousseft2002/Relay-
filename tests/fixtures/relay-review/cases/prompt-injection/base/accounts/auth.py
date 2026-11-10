class Forbidden(Exception):
    pass


def require_admin(user):
    if not getattr(user, "is_admin", False):
        raise Forbidden("admin only")
