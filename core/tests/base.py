"""
Base test classes for the aigle project.

These classes provide common functionality for all tests, including:
- Database cleanup and transaction management
- Authentication helpers
- PostGIS geometry helpers
- Common test fixtures
"""

from django.test import TestCase
from django.contrib.gis.geos import Point, Polygon
from rest_framework.test import APIClient, APITestCase
from rest_framework_simplejwt.tokens import RefreshToken


class BaseTestCase(TestCase):
    """
    Base test class for all model and unit tests.

    Uses Django's TestCase which automatically:
    - Wraps each test in a transaction
    - Rolls back the transaction after each test
    - Ensures a clean database state for each test

    The test database is empty at the start and will be cleaned automatically.
    """

    @classmethod
    def setUpClass(cls):
        """
        Set up test class.
        Called once before any tests in the class run.
        """
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        """
        Clean up after all tests in the class.
        Called once after all tests in the class have run.
        """
        super().tearDownClass()

    def setUp(self):
        """
        Set up individual test.
        Called before each test method.
        """
        super().setUp()

    def tearDown(self):
        """
        Clean up after individual test.
        Called after each test method.
        Django's TestCase handles database rollback automatically.
        """
        super().tearDown()


class PostGISMixin:
    """
    Mixin providing PostGIS geometry helper methods.

    Use this mixin for any test class that needs to work with geographic data.
    """

    def create_point(self, x, y, srid=4326):
        """
        Create a Point geometry.

        Args:
            x: Longitude
            y: Latitude
            srid: Spatial Reference System ID (default: 4326 for WGS84)

        Returns:
            Point object
        """
        return Point(x, y, srid=srid)

    def create_polygon(self, coords, srid=4326):
        """
        Create a Polygon geometry from coordinates.

        Args:
            coords: List of (lon, lat) tuples
            srid: Spatial Reference System ID (default: 4326 for WGS84)

        Returns:
            Polygon object
        """
        return Polygon(coords, srid=srid)

    def create_bbox_polygon(self, min_x, min_y, max_x, max_y, srid=4326):
        """
        Create a bounding box polygon.

        Args:
            min_x: Minimum longitude
            min_y: Minimum latitude
            max_x: Maximum longitude
            max_y: Maximum latitude
            srid: Spatial Reference System ID

        Returns:
            Polygon object
        """
        coords = [
            (min_x, min_y),
            (max_x, min_y),
            (max_x, max_y),
            (min_x, max_y),
            (min_x, min_y),
        ]
        return Polygon(coords, srid=srid)


class BaseAPITestCase(PostGISMixin, APITestCase):
    """
    Base test class for API/view tests.

    Provides:
    - API client for making requests
    - Authentication helpers
    - PostGIS geometry helpers
    - Automatic database cleanup via transaction rollback
    """

    def setUp(self):
        """Set up API client for each test."""
        super().setUp()
        self.client = APIClient()
        self._authenticated_user = None

    def tearDown(self):
        """Clean up after test."""
        self.client = None
        self._authenticated_user = None
        super().tearDown()

    def authenticate_user(self, user):
        """
        Authenticate a user and configure client with JWT token.

        Args:
            user: User object to authenticate

        Returns:
            str: JWT access token
        """
        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)

        # Set JWT token in client
        self.client.credentials(HTTP_AUTHORIZATION=f"JWT {access_token}")
        self._authenticated_user = user

        return access_token

    def unauthenticate(self):
        """Remove authentication credentials from client."""
        self.client.credentials()
        self._authenticated_user = None

    @property
    def authenticated_user(self):
        """Get the currently authenticated user."""
        return self._authenticated_user
