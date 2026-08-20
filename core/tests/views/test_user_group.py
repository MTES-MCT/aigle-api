import uuid

from django.db import IntegrityError, transaction
from django.urls import reverse
from rest_framework import status

from core.models.user_group import FeatureFlag, UserGroup, UserGroupType
from core.tests.base import BaseAPITestCase
from core.tests.fixtures.detection_data import create_object_type_category
from core.tests.fixtures.geo_data import create_herault_department
from core.tests.fixtures.users import (
    create_super_admin,
    create_admin,
    create_regular_user,
    create_user_group,
)


class UserGroupViewSetTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="ugadmin@test.com")
        self.admin = create_admin(email="ugmod@test.com")
        self.regular = create_regular_user(email="uguser@test.com")
        self.group_1 = create_user_group(name="DDTM Hérault")
        self.group_2 = create_user_group(name="Collectivité Montpellier")

    def test_list_as_super_admin(self):
        self.authenticate_user(self.super_admin)
        url = reverse("UserGroupViewSet-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)
        self.assertGreaterEqual(len(response.data), 2)

    def test_list_unauthenticated(self):
        url = reverse("UserGroupViewSet-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_retrieve(self):
        self.authenticate_user(self.super_admin)
        url = reverse(
            "UserGroupViewSet-detail", kwargs={"uuid": str(self.group_1.uuid)}
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "DDTM Hérault")

    def test_retrieve_nonexistent_returns_404(self):
        self.authenticate_user(self.super_admin)
        url = reverse("UserGroupViewSet-detail", kwargs={"uuid": str(uuid.uuid4())})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_search_by_name(self):
        self.authenticate_user(self.super_admin)
        url = reverse("UserGroupViewSet-list")
        response = self.client.get(url, {"q": "Hérault"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [r["name"] for r in response.data]
        self.assertIn("DDTM Hérault", names)

    def test_create_as_regular_forbidden(self):
        self.authenticate_user(self.regular)
        url = reverse("UserGroupViewSet-list")
        data = {"name": "New Group"}
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_as_regular_forbidden(self):
        self.authenticate_user(self.regular)
        url = reverse(
            "UserGroupViewSet-detail", kwargs={"uuid": str(self.group_2.uuid)}
        )
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class UserGroupFeatureFlagsTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="ugff-admin@test.com")
        self.regular = create_regular_user(email="ugff-user@test.com")
        self.department = create_herault_department()
        self.category = create_object_type_category(name="FF Category")
        self.group = create_user_group(name="FF Group")

    def _payload(self, **overrides):
        return {
            "name": "FF Created Group",
            "user_group_type": UserGroupType.DDTM,
            "departments_uuids": [str(self.department.uuid)],
            "object_type_categories_uuids": [str(self.category.uuid)],
            **overrides,
        }

    def test_catalogue_lists_every_feature_flag(self):
        self.authenticate_user(self.regular)
        url = reverse("UserGroupViewSet-feature-flags")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data,
            [{"value": value, "label": label} for value, label in FeatureFlag.choices],
        )
        self.assertIn(
            {"value": "STATS", "label": "Statistiques"},
            response.data,
        )

    def test_catalogue_unauthenticated(self):
        url = reverse("UserGroupViewSet-feature-flags")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_retrieve_exposes_feature_flags(self):
        self.group.feature_flags = [FeatureFlag.STATS]
        self.group.save()

        self.authenticate_user(self.super_admin)
        url = reverse("UserGroupViewSet-detail", kwargs={"uuid": str(self.group.uuid)})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["feature_flags"], ["STATS"])

    def test_defaults_to_no_feature_flag(self):
        self.authenticate_user(self.super_admin)
        url = reverse("UserGroupViewSet-list")
        response = self.client.post(url, self._payload(), format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        created = UserGroup.objects.get(name="FF Created Group")
        self.assertEqual(created.feature_flags, [])

    def test_create_with_feature_flags(self):
        self.authenticate_user(self.super_admin)
        url = reverse("UserGroupViewSet-list")
        response = self.client.post(
            url, self._payload(feature_flags=["STATS"]), format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        created = UserGroup.objects.get(name="FF Created Group")
        self.assertEqual(created.feature_flags, ["STATS"])

    def test_create_rejects_unknown_feature_flag(self):
        self.authenticate_user(self.super_admin)
        url = reverse("UserGroupViewSet-list")
        response = self.client.post(
            url, self._payload(feature_flags=["NOPE"]), format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("featureFlags", response.json())

    def test_create_rejects_duplicated_feature_flags(self):
        self.authenticate_user(self.super_admin)
        url = reverse("UserGroupViewSet-list")
        response = self.client.post(
            url, self._payload(feature_flags=["STATS", "STATS"]), format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("featureFlags", response.json())
        self.assertFalse(UserGroup.objects.filter(name="FF Created Group").exists())

    def test_update_feature_flags(self):
        self.group.feature_flags = [FeatureFlag.STATS]
        self.group.save()

        self.authenticate_user(self.super_admin)
        url = reverse("UserGroupViewSet-detail", kwargs={"uuid": str(self.group.uuid)})
        response = self.client.patch(
            url,
            self._payload(name=self.group.name, feature_flags=[]),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.group.refresh_from_db()
        self.assertEqual(self.group.feature_flags, [])

    def test_update_as_regular_forbidden(self):
        self.authenticate_user(self.regular)
        url = reverse("UserGroupViewSet-detail", kwargs={"uuid": str(self.group.uuid)})
        response = self.client.patch(url, {"feature_flags": ["STATS"]}, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_database_rejects_duplicated_feature_flags(self):
        # The serializer is not the only writer: management commands and the shell
        # write the field too, so the invariant lives in the database as well.
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                UserGroup.objects.create(
                    name="FF Duplicated",
                    user_group_type=UserGroupType.DDTM,
                    feature_flags=["STATS", "STATS"],
                )
