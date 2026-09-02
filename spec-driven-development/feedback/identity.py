"""Lightweight "who am I" handling (spec §2.1, §8).

There is no authentication. Identifying yourself is picking or typing a name;
the chosen `User.id` is kept in the Django session cookie. This is a claim,
not a credential -- the tool is internal and trust-based by design.
"""

import functools

from django.shortcuts import redirect

SESSION_KEY = "user_id"


def get_current_user(request):
    """The `User` for this session, or None if nobody has identified yet."""
    from .models import User

    user_id = request.session.get(SESSION_KEY)
    if user_id is None:
        return None
    user = User.objects.filter(pk=user_id).first()
    if user is None:
        # The row was removed out from under the session; treat as signed out.
        request.session.pop(SESSION_KEY, None)
    return user


def set_current_user(request, user):
    request.session[SESSION_KEY] = user.pk


def clear_current_user(request):
    request.session.pop(SESSION_KEY, None)


def requires_identity(view):
    """Send anyone without a name to the identify screen first."""

    @functools.wraps(view)
    def wrapper(request, *args, **kwargs):
        user = get_current_user(request)
        if user is None:
            return redirect("identify")
        return view(request, user, *args, **kwargs)

    return wrapper
