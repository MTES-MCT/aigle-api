import uuid

from django.urls import reverse
from rest_framework import status

from core.tests.base import BaseAPITestCase
from core.tests.fixtures.users import (
    create_super_admin,
    create_admin,
    create_regular_user,
)
from core.tests.fixtures.detection_data import (
    create_object_type,
    create_object_type_with_category,
)


class ObjectTypeViewSetTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="otadmin@test.com")
        self.admin = create_admin(email="otmod@test.com")
        self.regular = create_regular_user(email="otuser@test.com")

        self.object_type, self.category = create_object_type_with_category(
            object_type_name="Swimming Pool",
            category_name="Leisure",
            color="#00FF00",
        )
        self.object_type_2 = create_object_type(name="Cabanisation", color="#FF0000")

    def test_list_authenticated(self):
        self.authenticate_user(self.regular)
        url = reverse("ObjectTypeViewSet-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)
        self.assertGreaterEqual(len(response.data), 2)

    def test_list_unauthenticated(self):
        url = reverse("ObjectTypeViewSet-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_retrieve(self):
        self.authenticate_user(self.regular)
        url = reverse(
            "ObjectTypeViewSet-detail", kwargs={"uuid": str(self.object_type.uuid)}
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Swimming Pool")

    def test_retrieve_nonexistent_returns_404(self):
        self.authenticate_user(self.regular)
        url = reverse("ObjectTypeViewSet-detail", kwargs={"uuid": str(uuid.uuid4())})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_search_by_name(self):
        self.authenticate_user(self.regular)
        url = reverse("ObjectTypeViewSet-list")
        response = self.client.get(url, {"q": "Swimming"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [r["name"] for r in response.data]
        self.assertIn("Swimming Pool", names)

    def test_create_as_regular_forbidden(self):
        self.authenticate_user(self.regular)
        url = reverse("ObjectTypeViewSet-list")
        data = {"name": "New Type", "color": "#ABCDEF"}
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_as_super_admin(self):
        self.authenticate_user(self.super_admin)
        url = reverse("ObjectTypeViewSet-list")
        data = {"name": "Boat", "color": "#123456"}
        response = self.client.post(url, data, format="json")
        self.assertIn(
            response.status_code, [status.HTTP_201_CREATED, status.HTTP_200_OK]
        )

    def test_delete_as_regular_forbidden(self):
        self.authenticate_user(self.regular)
        url = reverse(
            "ObjectTypeViewSet-detail", kwargs={"uuid": str(self.object_type_2.uuid)}
        )
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
