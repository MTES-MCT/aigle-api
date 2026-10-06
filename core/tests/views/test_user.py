from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status

from core.services.path_validation_progress import PathValidationProgressService
from core.tests.base import BaseAPITestCase
from core.tests.fixtures.users import (
    add_user_to_group,
    create_super_admin,
    create_admin,
    create_regular_user,
    create_deactivated_user,
    create_user_group,
)
from core.models import User, UserRole, UserUserGroup
from core.models.user_group import FeatureFlag, UserGroupRight


class UserViewSetTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="superadmin@test.com")
        self.admin = create_admin(email="admin@test.com")
        self.regular = create_regular_user(email="regular@test.com")
        self.deactivated = create_deactivated_user(email="deactivated@test.com")

    def test_get_current_user_authenticated(self):
        self.authenticate_user(self.regular)
        url = reverse("UserViewSet-get-me")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], self.regular.email)

    def test_get_current_user_unauthenticated(self):
        url = reverse("UserViewSet-get-me")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_current_user_deactivated(self):
        self.authenticate_user(self.deactivated)
        url = reverse("UserViewSet-get-me")
        response = self.client.get(url)
        self.assertIn(
            response.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )

    def test_list_users_as_admin(self):
        self.authenticate_user(self.admin)
        url = reverse("UserViewSet-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)

    def test_list_users_as_regular(self):
        self.authenticate_user(self.regular)
        url = reverse("UserViewSet-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_retrieve_user_as_super_admin(self):
        self.authenticate_user(self.super_admin)
        url = reverse("UserViewSet-detail", kwargs={"uuid": str(self.admin.uuid)})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], self.admin.email)

    def test_filter_users_by_email(self):
        self.authenticate_user(self.super_admin)
        url = reverse("UserViewSet-list")
        response = self.client.get(url, {"email": "admin"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        emails = [r["email"] for r in response.data]
        self.assertTrue(any("admin" in email for email in emails))

    def test_filter_users_by_role(self):
        self.authenticate_user(self.super_admin)
        url = reverse("UserViewSet-list")
        response = self.client.get(url, {"roles": UserRole.ADMIN})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for user_data in response.data:
            self.assertEqual(
                user_data.get("userRole") or user_data.get("user_role"),
                UserRole.ADMIN,
            )

    def test_user_ordering(self):
        self.authenticate_user(self.admin)
        url = reverse("UserViewSet-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data
        if len(results) > 1:
            first_user = User.objects.get(email=results[0]["email"])
            second_user = User.objects.get(email=results[1]["email"])
            self.assertGreaterEqual(first_user.id, second_user.id)

    def test_user_response_includes_user_groups(self):
        self.authenticate_user(self.super_admin)
        url = reverse("UserViewSet-detail", kwargs={"uuid": str(self.admin.uuid)})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        has_groups = (
            "userUserGroups" in response.data or "user_user_groups" in response.data
        )
        self.assertTrue(has_groups)

    def test_cannot_access_other_users_via_me_endpoint(self):
        self.authenticate_user(self.regular)
        url = reverse("UserViewSet-get-me")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], self.regular.email)
        self.assertNotEqual(response.data["email"], self.admin.email)

    def test_user_password_not_in_response(self):
        self.authenticate_user(self.super_admin)
        url = reverse("UserViewSet-detail", kwargs={"uuid": str(self.admin.uuid)})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("password", response.data)

    def test_super_admin_can_access_all_users(self):
        self.authenticate_user(self.super_admin)
        url = reverse("UserViewSet-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data), 3)


class UserWritePasswordTests(BaseAPITestCase):
    """The write responses used to echo the stored password hash. The password stays
    required on create and on PUT, optional on PATCH."""

    PASSWORD = "Password123!"

    def setUp(self):
        super().setUp()
        self.authenticate_user(create_super_admin(email="pw-sa@test.com"))
        self.user = create_regular_user(email="pw-regular@test.com")
        self.detail_url = reverse(
            "UserViewSet-detail", kwargs={"uuid": str(self.user.uuid)}
        )

    def _payload(self, **overrides):
        return {
            "email": "pw-new@test.com",
            "userRole": "REGULAR",
            "password": self.PASSWORD,
            "userUserGroups": [],
            **overrides,
        }

    def test_create_does_not_return_the_password(self):
        response = self.client.post(
            reverse("UserViewSet-list"), self._payload(), format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertNotIn("password", response.json())
        self.assertTrue(
            User.objects.get(email="pw-new@test.com").check_password(self.PASSWORD)
        )

    def test_create_requires_a_password(self):
        payload = self._payload()
        del payload["password"]

        response = self.client.post(reverse("UserViewSet-list"), payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password", response.json())

    def test_patch_does_not_return_the_password(self):
        response = self.client.patch(
            self.detail_url, {"password": self.PASSWORD}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("password", response.json())
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.PASSWORD))

    def test_patch_without_password_keeps_it(self):
        response = self.client.patch(
            self.detail_url, {"email": "pw-renamed@test.com"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("password", response.json())
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "pw-renamed@test.com")
        self.assertTrue(self.user.check_password("userpass123"))

    def test_put_does_not_return_the_password(self):
        response = self.client.put(
            self.detail_url, self._payload(email=self.user.email), format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("password", response.json())
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.PASSWORD))

    def test_put_requires_a_password(self):
        payload = self._payload(email=self.user.email)
        del payload["password"]

        response = self.client.put(self.detail_url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password", response.json())


class UserFeatureFlagsTests(BaseAPITestCase):
    """/users/me carries the union of the feature flags of every group the user
    belongs to: the frontend shows or hides features from that single list."""

    def setUp(self):
        super().setUp()
        self.user = create_regular_user(email="ff-user@test.com")
        self.url = reverse("UserViewSet-get-me")

    def test_no_group_means_no_feature_flag(self):
        self.authenticate_user(self.user)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["feature_flags"], [])

    def test_group_without_flag_means_no_feature_flag(self):
        add_user_to_group(self.user, create_user_group(name="FF Plain"))

        self.authenticate_user(self.user)
        response = self.client.get(self.url)

        self.assertEqual(response.data["feature_flags"], [])

    def test_one_group_with_the_flag_is_enough(self):
        plain = create_user_group(name="FF Plain")
        with_flag = create_user_group(name="FF With Stats")
        with_flag.feature_flags = [FeatureFlag.STATS]
        with_flag.save()
        add_user_to_group(self.user, plain)
        add_user_to_group(self.user, with_flag)

        self.authenticate_user(self.user)
        response = self.client.get(self.url)

        self.assertEqual(response.data["feature_flags"], ["STATS"])

    def test_flag_shared_by_two_groups_is_returned_once(self):
        for name in ["FF Stats A", "FF Stats B"]:
            group = create_user_group(name=name)
            group.feature_flags = [FeatureFlag.STATS]
            group.save()
            add_user_to_group(self.user, group)

        self.authenticate_user(self.user)
        response = self.client.get(self.url)

        self.assertEqual(response.data["feature_flags"], ["STATS"])

    def test_user_list_exposes_feature_flags(self):
        group = create_user_group(name="FF Listed")
        group.feature_flags = [FeatureFlag.STATS]
        group.save()
        add_user_to_group(self.user, group)

        self.authenticate_user(create_super_admin(email="ff-admin@test.com"))
        response = self.client.get(reverse("UserViewSet-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        listed = next(
            item for item in response.data if item["email"] == self.user.email
        )
        self.assertEqual(listed["feature_flags"], ["STATS"])


class UserPathValidationTests(BaseAPITestCase):
    """/users/me/ stays lean: only the admin list and detail join the progress row."""

    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="pv-admin@test.com")
        self.started = create_regular_user(email="pv-started@test.com")
        self.never_started = create_regular_user(email="pv-never@test.com")
        PathValidationProgressService.apply(
            user=self.started, item_count=11, check=[0, 1], uncheck=[]
        )

    def listed(self, response, user):
        return next(item for item in response.data if item["email"] == user.email)

    def test_list_exposes_path_validation(self):
        self.authenticate_user(self.super_admin)
        response = self.client.get(reverse("UserViewSet-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(self.listed(response, self.never_started)["path_validation"])
        path_validation = self.listed(response, self.started)["path_validation"]
        self.assertIsInstance(path_validation.pop("updated_at"), str)
        self.assertEqual(
            path_validation,
            {
                "checked_items": [0, 1],
                "checked_count": 2,
                "item_count": 11,
                "completed_at": None,
            },
        )

    def test_list_query_count_does_not_grow_with_progress_rows(self):
        self.authenticate_user(self.super_admin)
        url = reverse("UserViewSet-list")

        with CaptureQueriesContext(connection) as with_one_row:
            self.client.get(url)

        for index in range(3):
            PathValidationProgressService.apply(
                user=create_regular_user(email=f"pv-more-{index}@test.com"),
                item_count=11,
                check=[index],
                uncheck=[],
            )

        with CaptureQueriesContext(connection) as with_four_rows:
            response = self.client.get(url)

        self.assertEqual(
            len([item for item in response.data if item["path_validation"]]), 4
        )
        self.assertEqual(
            len(with_four_rows.captured_queries), len(with_one_row.captured_queries)
        )

    def test_retrieve_exposes_path_validation(self):
        self.authenticate_user(self.super_admin)
        response = self.client.get(
            reverse("UserViewSet-detail", kwargs={"uuid": str(self.started.uuid)})
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["path_validation"]["checked_items"], [0, 1])

    def test_me_does_not_read_path_validation(self):
        self.authenticate_user(self.started)

        with CaptureQueriesContext(connection) as context:
            response = self.client.get(reverse("UserViewSet-get-me"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("path_validation", response.data)
        self.assertFalse(
            any(
                "core_pathvalidationprogress" in query["sql"]
                for query in context.captured_queries
            )
        )

    def test_admin_list_keeps_its_scope(self):
        admin = create_admin(email="pv-group-admin@test.com")
        group = create_user_group(name="PV Admin Group")
        add_user_to_group(admin, group)
        add_user_to_group(self.started, group)
        in_group_never_started = create_regular_user(email="pv-in-group@test.com")
        add_user_to_group(in_group_never_started, group)
        add_user_to_group(self.never_started, create_user_group(name="PV Other Group"))
        other_admin = create_admin(email="pv-other-admin@test.com")
        add_user_to_group(other_admin, group)
        PathValidationProgressService.apply(
            user=other_admin, item_count=11, check=[0], uncheck=[]
        )

        self.authenticate_user(admin)
        response = self.client.get(reverse("UserViewSet-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            {
                item["email"]: item["path_validation"] is not None
                for item in response.data
            },
            {self.started.email: True, in_group_never_started.email: False},
        )
        self.assertEqual(
            self.listed(response, self.started)["path_validation"]["checked_items"],
            [0, 1],
        )


class UserIsStaffPermissionTests(BaseAPITestCase):
    """is_staff ("Utilisateur interne") opens the statistics, drops the user from the
    DDTM activity counts and allows the Django admin login: only a SUPER_ADMIN may set
    it. An ADMIN may still send the current value back (the form posts every field)."""

    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="staff-sa@test.com")
        self.admin = create_admin(email="staff-admin@test.com")
        self.group = create_user_group(name="Staff Group")
        add_user_to_group(self.admin, self.group)
        self.regular = create_regular_user(email="staff-regular@test.com")
        add_user_to_group(self.regular, self.group)
        self.staff = create_regular_user(email="staff-internal@test.com")
        self.staff.is_staff = True
        self.staff.save()
        add_user_to_group(self.staff, self.group)

    def _create(self, email, is_staff):
        return self.client.post(
            reverse("UserViewSet-list"),
            {
                "email": email,
                "userRole": "REGULAR",
                "password": "Password123!",
                "isStaff": is_staff,
                "userUserGroups": [],
            },
            format="json",
        )

    def _patch(self, user, payload):
        return self.client.patch(
            reverse("UserViewSet-detail", kwargs={"uuid": str(user.uuid)}),
            payload,
            format="json",
        )

    def test_admin_cannot_create_an_internal_user(self):
        self.authenticate_user(self.admin)

        response = self._create("staff-new@test.com", True)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(User.objects.filter(email="staff-new@test.com").exists())

    def test_admin_can_create_a_non_internal_user(self):
        self.authenticate_user(self.admin)

        response = self._create("staff-new@test.com", False)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(User.objects.get(email="staff-new@test.com").is_staff)

    def test_super_admin_can_create_an_internal_user(self):
        self.authenticate_user(self.super_admin)

        response = self._create("staff-new@test.com", True)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(User.objects.get(email="staff-new@test.com").is_staff)

    def test_admin_cannot_flag_a_user_as_internal(self):
        self.authenticate_user(self.admin)

        response = self._patch(self.regular, {"isStaff": True})

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.regular.refresh_from_db()
        self.assertFalse(self.regular.is_staff)

    def test_admin_cannot_unflag_an_internal_user(self):
        self.authenticate_user(self.admin)

        response = self._patch(self.staff, {"isStaff": False})

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.staff.refresh_from_db()
        self.assertTrue(self.staff.is_staff)

    def test_admin_can_resend_the_current_value(self):
        self.authenticate_user(self.admin)

        response = self._patch(
            self.staff, {"email": "staff-renamed@test.com", "isStaff": True}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.staff.refresh_from_db()
        self.assertEqual(self.staff.email, "staff-renamed@test.com")
        self.assertTrue(self.staff.is_staff)

    def test_super_admin_can_flag_a_user_as_internal(self):
        self.authenticate_user(self.super_admin)

        response = self._patch(self.regular, {"isStaff": True})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.regular.refresh_from_db()
        self.assertTrue(self.regular.is_staff)


class UserForeignGroupMembershipTests(BaseAPITestCase):
    """An ADMIN administers the groups they belong to. Memberships of the edited user in
    any other group are left as they are: the form sends them back unchanged, and adding,
    changing or emptying one is refused."""

    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="foreign-sa@test.com")
        self.admin = create_admin(email="foreign-admin@test.com")
        self.own_group = create_user_group(name="Foreign Own Group")
        self.other_own_group = create_user_group(name="Foreign Other Own Group")
        self.foreign_group = create_user_group(name="Foreign Group")
        add_user_to_group(self.admin, self.own_group)
        add_user_to_group(self.admin, self.other_own_group)

        self.member = create_regular_user(email="foreign-member@test.com")
        add_user_to_group(self.member, self.own_group)
        UserUserGroup.objects.create(
            user=self.member,
            user_group=self.foreign_group,
            user_group_rights=[UserGroupRight.READ, UserGroupRight.ANNOTATE],
        )

    def _membership(self, group, rights):
        return {"userGroupUuid": str(group.uuid), "userGroupRights": rights}

    def _patch(self, user_user_groups):
        return self.client.patch(
            reverse("UserViewSet-detail", kwargs={"uuid": str(self.member.uuid)}),
            {"userUserGroups": user_user_groups},
            format="json",
        )

    def _rights_by_group(self):
        return {
            uug.user_group_id: sorted(uug.user_group_rights)
            for uug in UserUserGroup.objects.filter(user=self.member)
        }

    def test_admin_cannot_create_a_user_in_a_foreign_group(self):
        self.authenticate_user(self.admin)

        response = self.client.post(
            reverse("UserViewSet-list"),
            {
                "email": "foreign-new@test.com",
                "userRole": "REGULAR",
                "password": "Password123!",
                "userUserGroups": [
                    self._membership(self.own_group, ["READ"]),
                    self._membership(self.foreign_group, ["READ"]),
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(User.objects.filter(email="foreign-new@test.com").exists())

    def test_admin_cannot_add_a_foreign_group(self):
        UserUserGroup.objects.filter(
            user=self.member, user_group=self.foreign_group
        ).delete()
        self.authenticate_user(self.admin)

        response = self._patch(
            [
                self._membership(self.own_group, ["READ", "WRITE"]),
                self._membership(self.foreign_group, ["READ"]),
            ]
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            self._rights_by_group(), {self.own_group.id: ["READ", "WRITE"]}
        )

    def test_admin_cannot_change_rights_in_a_foreign_group(self):
        self.authenticate_user(self.admin)

        response = self._patch(
            [
                self._membership(self.own_group, ["READ"]),
                self._membership(self.foreign_group, ["READ", "ANNOTATE", "WRITE"]),
            ]
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            self._rights_by_group(),
            {
                self.own_group.id: ["READ", "WRITE"],
                self.foreign_group.id: ["ANNOTATE", "READ"],
            },
        )

    def test_admin_cannot_remove_a_foreign_membership_by_emptying_its_rights(self):
        self.authenticate_user(self.admin)

        response = self._patch(
            [
                self._membership(self.own_group, ["READ", "WRITE"]),
                self._membership(self.foreign_group, []),
            ]
        )

        # Empty rights never reach the service: the input serializer refuses them.
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            self._rights_by_group()[self.foreign_group.id], ["ANNOTATE", "READ"]
        )

    def test_patch_omitting_a_foreign_membership_keeps_it(self):
        self.authenticate_user(self.admin)

        response = self._patch([self._membership(self.own_group, ["READ"])])

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            self._rights_by_group(),
            {
                self.own_group.id: ["READ"],
                self.foreign_group.id: ["ANNOTATE", "READ"],
            },
        )

    def test_admin_can_send_a_foreign_membership_back_unchanged(self):
        self.authenticate_user(self.admin)

        response = self._patch(
            [
                self._membership(self.own_group, ["READ"]),
                self._membership(self.foreign_group, ["ANNOTATE", "READ"]),
            ]
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            self._rights_by_group(),
            {
                self.own_group.id: ["READ"],
                self.foreign_group.id: ["ANNOTATE", "READ"],
            },
        )

    def test_admin_can_move_a_user_between_own_groups(self):
        self.authenticate_user(self.admin)

        response = self._patch(
            [
                self._membership(self.other_own_group, ["READ"]),
                self._membership(self.foreign_group, ["READ", "ANNOTATE"]),
            ]
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            self._rights_by_group(),
            {
                self.other_own_group.id: ["READ"],
                self.foreign_group.id: ["ANNOTATE", "READ"],
            },
        )

    def test_admin_can_manage_a_user_in_several_own_groups(self):
        add_user_to_group(self.member, self.other_own_group)
        self.authenticate_user(self.admin)

        list_response = self.client.get(reverse("UserViewSet-list"))
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [user["email"] for user in list_response.data],
            [self.member.email],
        )
        self.assertEqual(self.client.get(reverse("UserViewSet-count")).data, 1)

        detail_url = reverse(
            "UserViewSet-detail", kwargs={"uuid": str(self.member.uuid)}
        )
        self.assertEqual(self.client.get(detail_url).status_code, status.HTTP_200_OK)

        response = self._patch([self._membership(self.own_group, ["READ"])])

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            self._rights_by_group(),
            {
                self.own_group.id: ["READ"],
                self.foreign_group.id: ["ANNOTATE", "READ"],
            },
        )

    def test_admin_can_create_a_user_in_own_group(self):
        self.authenticate_user(self.admin)

        response = self.client.post(
            reverse("UserViewSet-list"),
            {
                "email": "foreign-new@test.com",
                "userRole": "REGULAR",
                "password": "Password123!",
                "userUserGroups": [self._membership(self.own_group, ["READ"])],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            list(
                UserUserGroup.objects.filter(
                    user__email="foreign-new@test.com"
                ).values_list("user_group_id", flat=True)
            ),
            [self.own_group.id],
        )

    def test_super_admin_replaces_every_membership(self):
        self.authenticate_user(self.super_admin)

        response = self._patch(
            [
                self._membership(self.own_group, ["READ"]),
                self._membership(self.other_own_group, ["READ", "WRITE"]),
            ]
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            self._rights_by_group(),
            {
                self.own_group.id: ["READ"],
                self.other_own_group.id: ["READ", "WRITE"],
            },
        )

    def test_super_admin_can_change_rights_in_any_group(self):
        self.authenticate_user(self.super_admin)

        response = self._patch(
            [
                self._membership(self.own_group, ["READ", "WRITE"]),
                self._membership(self.foreign_group, ["WRITE"]),
            ]
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._rights_by_group()[self.foreign_group.id], ["WRITE"])
