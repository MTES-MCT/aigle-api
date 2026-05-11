from django.urls import reverse
from rest_framework import status

from core.tests.base import BaseAPITestCase
from core.tests.fixtures.users import (
    create_super_admin,
    create_admin,
    create_regular_user,
)


class CommandAsyncViewSetTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="rcadmin@test.com")
        self.admin = create_admin(email="rcmod@test.com")
        self.regular = create_regular_user(email="rcuser@test.com")

    def test_list_as_super_admin(self):
        self.authenticate_user(self.super_admin)
        url = reverse("CommandAsyncViewSet-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_as_admin(self):
        self.authenticate_user(self.admin)
        url = reverse("CommandAsyncViewSet-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_as_regular(self):
        self.authenticate_user(self.regular)
        url = reverse("CommandAsyncViewSet-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_unauthenticated(self):
        url = reverse("CommandAsyncViewSet-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
