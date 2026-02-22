"""
dynamo_backend.auth_backend
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Authentication backend for DynamoUser.

Replaces django.contrib.auth.backends.ModelBackend so that permission
checks never touch the M2M Group / Permission tables.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model


class DynamoAuthBackend:
    """
    Authenticates against DynamoUser and delegates permission checks to
    the user's own has_perm / has_module_perms methods.

    No Group or Permission M2M queries are ever issued.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        if username is None or password is None:
            return None
        try:
            user = UserModel._default_manager.get_by_natural_key(username)
        except UserModel.DoesNotExist:
            # Run the default password hasher to reduce timing attacks
            UserModel().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None

    def user_can_authenticate(self, user):
        return getattr(user, "is_active", True)

    def get_user(self, user_id):
        UserModel = get_user_model()
        try:
            user = UserModel._default_manager.get(pk=user_id)
        except UserModel.DoesNotExist:
            return None
        return user if self.user_can_authenticate(user) else None

    # ── permission methods ───────────────────────────────────────────────

    def has_perm(self, user_obj, perm, obj=None):
        if not user_obj.is_active:
            return False
        return user_obj.has_perm(perm, obj)

    def has_module_perms(self, user_obj, app_label):
        if not user_obj.is_active:
            return False
        return user_obj.has_module_perms(app_label)

    def get_all_permissions(self, user_obj, obj=None):
        return set()

    def get_group_permissions(self, user_obj, obj=None):
        return set()
