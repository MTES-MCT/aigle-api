from datetime import timedelta

from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from core.models.analytic_log import AnalyticLog, AnalyticLogType
from core.models.user import User, UserRole
from core.tests.base import BaseTestCase
from core.tests.fixtures.users import create_super_admin, create_user


def create_old_user(email, last_login=None, **kwargs):
    user = create_user(email=email, **kwargs)
    # created_at is auto_now_add: backdate through a queryset update.
    User.objects.filter(pk=user.pk).update(
        created_at=timezone.now() - timedelta(days=800), last_login=last_login
    )
    return user


def log_access(user, when):
    log = AnalyticLog.objects.create(
        user=user, analytic_log_type=AnalyticLogType.USER_ACCESS
    )
    AnalyticLog.objects.filter(pk=log.pk).update(created_at=when)


def role(user):
    return User.objects.get(pk=user.pk).user_role


class DeactivateInactiveUsersCommandTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        now = timezone.now()
        self.long_ago = now - timedelta(days=400)
        self.recently = now - timedelta(days=30)

    def test_deactivates_user_without_login_nor_access(self):
        user = create_old_user("old@test.com", last_login=self.long_ago)
        log_access(user, self.long_ago)

        call_command("deactivate_inactive_users")

        self.assertEqual(role(user), UserRole.DEACTIVATED)
        last_history = User.history.filter(id=user.pk).latest("history_date")
        self.assertEqual(last_history.history_change_reason, "INACTIVITY")

    def test_deactivates_old_account_that_never_logged_in(self):
        user = create_old_user("never@test.com", user_role=UserRole.ADMIN)

        call_command("deactivate_inactive_users")

        self.assertEqual(role(user), UserRole.DEACTIVATED)

    def test_keeps_recent_login(self):
        user = create_old_user("login@test.com", last_login=self.recently)

        call_command("deactivate_inactive_users")

        self.assertEqual(role(user), UserRole.REGULAR)

    def test_keeps_recent_app_access_despite_old_login(self):
        # Refresh token rotation keeps a daily user signed in without a new login.
        user = create_old_user("refresh@test.com", last_login=self.long_ago)
        log_access(user, self.recently)

        call_command("deactivate_inactive_users")

        self.assertEqual(role(user), UserRole.REGULAR)

    def test_keeps_account_created_within_the_period(self):
        user = create_user(email="new@test.com")

        call_command("deactivate_inactive_users")

        self.assertEqual(role(user), UserRole.REGULAR)

    def test_skips_super_admins_and_deleted_users(self):
        super_admin = create_super_admin()
        User.objects.filter(pk=super_admin.pk).update(
            created_at=self.long_ago, last_login=self.long_ago
        )
        deleted = create_old_user("deleted@test.com")
        User.objects.filter(pk=deleted.pk).update(deleted=True)

        call_command("deactivate_inactive_users")

        self.assertEqual(role(super_admin), UserRole.SUPER_ADMIN)
        self.assertEqual(role(deleted), UserRole.REGULAR)

    def test_days_option(self):
        user = create_old_user("days@test.com", last_login=self.recently)

        call_command("deactivate_inactive_users", days=20)

        self.assertEqual(role(user), UserRole.DEACTIVATED)

    def test_dry_run_changes_nothing(self):
        user = create_old_user("dry@test.com", last_login=self.long_ago)

        call_command("deactivate_inactive_users", dry_run=True)

        self.assertEqual(role(user), UserRole.REGULAR)

    def test_rejects_non_positive_days(self):
        with self.assertRaises(CommandError):
            call_command("deactivate_inactive_users", days=0)
