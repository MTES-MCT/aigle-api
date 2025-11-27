"""
Tests for ExternalAPITestView.

Tests cover:
- GET request with valid API key
- POST request with valid API key
- Request without API key (unauthorized)
- Request with invalid API key
- Response format validation
"""

from django.urls import reverse
from rest_framework import status

from core.tests.base import BaseAPITestCase
from core.tests.fixtures.users import create_api_key


class ExternalAPITestViewTests(BaseAPITestCase):
    """Tests for ExternalAPITestView."""

    def setUp(self):
        """Set up test data."""
        super().setUp()

        # Create API key for testing
        self.api_key_obj, self.api_key = create_api_key(name="Test API Key")

    def test_get_request_with_valid_api_key(self):
        """Test GET request with valid API key returns success."""
        url = reverse("ExternalAPITestView")

        # Set API key in Authorization header
        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {self.api_key}")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("message", response.data)
        self.assertIn("status", response.data)
        self.assertEqual(response.data["status"], "success")

    def test_get_request_without_api_key(self):
        """Test GET request without API key returns unauthorized."""
        url = reverse("ExternalAPITestView")

        # No API key in header
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_request_with_invalid_api_key(self):
        """Test GET request with invalid API key returns unauthorized."""
        url = reverse("ExternalAPITestView")

        # Set invalid API key
        self.client.credentials(HTTP_AUTHORIZATION="Api-Key invalid-key-12345")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_post_request_with_valid_api_key(self):
        """Test POST request with valid API key returns success."""
        url = reverse("ExternalAPITestView")

        # Set API key in Authorization header
        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {self.api_key}")

        post_data = {"test_field": "test_value", "number": 42}

        response = self.client.post(url, post_data, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("message", response.data)
        self.assertIn("status", response.data)
        self.assertEqual(response.data["status"], "success")
        self.assertIn("received_data", response.data)
        self.assertEqual(response.data["received_data"]["test_field"], "test_value")

    def test_post_request_without_api_key(self):
        """Test POST request without API key returns unauthorized."""
        url = reverse("ExternalAPITestView")

        post_data = {"test": "data"}
        response = self.client.post(url, post_data, format="json")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_response_includes_timestamp(self):
        """Test GET response includes timestamp in data."""
        url = reverse("ExternalAPITestView")

        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {self.api_key}")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("data", response.data)
        self.assertIn("timestamp", response.data["data"])

    def test_post_echoes_received_data(self):
        """Test POST response echoes back the received data."""
        url = reverse("ExternalAPITestView")

        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {self.api_key}")

        post_data = {"field1": "value1", "field2": "value2", "nested": {"key": "value"}}

        response = self.client.post(url, post_data, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("received_data", response.data)
        self.assertEqual(response.data["received_data"]["field_1"], "value1")
        self.assertEqual(response.data["received_data"]["field_2"], "value2")
        self.assertEqual(response.data["received_data"]["nested"]["key"], "value")

    def test_jwt_token_does_not_work(self):
        """Test that JWT token authentication doesn't work for this endpoint."""
        from core.tests.fixtures.users import create_regular_user

        url = reverse("ExternalAPITestView")

        # Create user and get JWT token
        user = create_regular_user()
        self.authenticate_user(user)

        # JWT authentication should not work for this endpoint
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_multiple_requests_with_same_api_key(self):
        """Test multiple requests with same API key all succeed."""
        url = reverse("ExternalAPITestView")

        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {self.api_key}")

        # Make multiple requests
        response1 = self.client.get(url)
        response2 = self.client.get(url)
        response3 = self.client.post(url, {"data": "test"}, format="json")

        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        self.assertEqual(response2.status_code, status.HTTP_200_OK)
        self.assertEqual(response3.status_code, status.HTTP_201_CREATED)

    def test_post_with_empty_data(self):
        """Test POST request with empty data."""
        url = reverse("ExternalAPITestView")

        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {self.api_key}")

        response = self.client.post(url, {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("received_data", response.data)
        self.assertEqual(response.data["received_data"], {})

    def test_revoked_api_key_fails(self):
        """Test that revoked API key no longer works."""
        url = reverse("ExternalAPITestView")

        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {self.api_key}")

        # First request should succeed
        response1 = self.client.get(url)
        self.assertEqual(response1.status_code, status.HTTP_200_OK)

        # Revoke the API key
        self.api_key_obj.revoked = True
        self.api_key_obj.save()

        # Second request should fail
        response2 = self.client.get(url)
        self.assertEqual(response2.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_api_key_header_format_variations(self):
        """Test different API key header format variations."""
        url = reverse("ExternalAPITestView")

        # Correct format: "Api-Key <key>"
        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {self.api_key}")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Wrong prefix should fail
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.api_key}")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        # No prefix should fail
        self.client.credentials(HTTP_AUTHORIZATION=self.api_key)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
