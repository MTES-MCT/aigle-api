"""Base test classes: auth helpers, PostGIS geometry helpers, transaction cleanup."""

from django.test import TestCase
from django.contrib.gis.geos import Point, Polygon
from rest_framework.test import APIClient, APITestCase
from rest_framework_simplejwt.tokens import RefreshToken


class BaseTestCase(TestCase):
    """Base for model/unit tests. Django TestCase wraps each test in a transaction rolled back after."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()

    def setUp(self):
        super().setUp()

    def tearDown(self):
        super().tearDown()


class PostGISMixin:
    """PostGIS geometry helpers for tests."""

    def create_point(self, x, y, srid=4326):
        return Point(x, y, srid=srid)

    def create_polygon(self, coords, srid=4326):
        return Polygon(coords, srid=srid)

    def create_bbox_polygon(self, min_x, min_y, max_x, max_y, srid=4326):
        coords = [
            (min_x, min_y),
            (max_x, min_y),
            (max_x, max_y),
            (min_x, max_y),
            (min_x, min_y),
        ]
        return Polygon(coords, srid=srid)


class BaseAPITestCase(PostGISMixin, APITestCase):
    """Base for API/view tests: API client, JWT auth helpers, PostGIS helpers."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self._authenticated_user = None

    def tearDown(self):
        self.client = None
        self._authenticated_user = None
        super().tearDown()

    def authenticate_user(self, user):
        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)

        self.client.credentials(HTTP_AUTHORIZATION=f"JWT {access_token}")
        self._authenticated_user = user

        return access_token

    def unauthenticate(self):
        self.client.credentials()
        self._authenticated_user = None

    @property
    def authenticated_user(self):
        return self._authenticated_user
