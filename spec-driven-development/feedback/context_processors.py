from .identity import get_current_user


def current_user(request):
    """Makes `current_user` available to every template (for the header)."""
    return {"current_user": get_current_user(request)}
