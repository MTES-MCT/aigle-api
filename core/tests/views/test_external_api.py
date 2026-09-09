from django.urls import reverse
from rest_framework import status

from core.tests.base import BaseAPITestCase
from core.tests.fixtures.users import create_api_key


from core.models.detection_data import DetectionControlStatus
from core.serializers.external_api import (
    UpdateControlStatusExternalApiInputSerializer,
)


class ExternalAPITestViewTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()

        self.api_key_obj, self.api_key = create_api_key(name="Test API Key")

    def test_get_request_with_valid_api_key(self):
        url = reverse("ExternalAPITestView")

        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {self.api_key}")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("message", response.data)
        self.assertIn("status", response.data)
        self.assertEqual(response.data["status"], "success")

    def test_get_request_without_api_key(self):
        url = reverse("ExternalAPITestView")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_request_with_invalid_api_key(self):
        url = reverse("ExternalAPITestView")

        self.client.credentials(HTTP_AUTHORIZATION="Api-Key invalid-key-12345")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_post_request_with_valid_api_key(self):
        url = reverse("ExternalAPITestView")

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
        url = reverse("ExternalAPITestView")

        post_data = {"test": "data"}
        response = self.client.post(url, post_data, format="json")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_response_includes_timestamp(self):
        url = reverse("ExternalAPITestView")

        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {self.api_key}")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("data", response.data)
        self.assertIn("timestamp", response.data["data"])

    def test_post_echoes_received_data(self):
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
        from core.tests.fixtures.users import create_regular_user

        url = reverse("ExternalAPITestView")

        user = create_regular_user()
        self.authenticate_user(user)

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_multiple_requests_with_same_api_key(self):
        url = reverse("ExternalAPITestView")

        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {self.api_key}")

        response1 = self.client.get(url)
        response2 = self.client.get(url)
        response3 = self.client.post(url, {"data": "test"}, format="json")

        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        self.assertEqual(response2.status_code, status.HTTP_200_OK)
        self.assertEqual(response3.status_code, status.HTTP_201_CREATED)

    def test_post_with_empty_data(self):
        url = reverse("ExternalAPITestView")

        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {self.api_key}")

        response = self.client.post(url, {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("received_data", response.data)
        self.assertEqual(response.data["received_data"], {})

    def test_revoked_api_key_fails(self):
        url = reverse("ExternalAPITestView")

        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {self.api_key}")

        response1 = self.client.get(url)
        self.assertEqual(response1.status_code, status.HTTP_200_OK)

        self.api_key_obj.revoked = True
        self.api_key_obj.save()

        response2 = self.client.get(url)
        self.assertEqual(response2.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_api_key_header_format_variations(self):
        url = reverse("ExternalAPITestView")

        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {self.api_key}")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.api_key}")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        self.client.credentials(HTTP_AUTHORIZATION=self.api_key)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class ExternalAPIUpdateControlStatusViewTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.api_key_obj, self.api_key = create_api_key(name="Update Control Key")
        self.url = reverse("ExternalAPIUpdateControlStatusView")

    def test_post_without_api_key(self):
        response = self.client.post(self.url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_post_with_invalid_api_key(self):
        self.client.credentials(HTTP_AUTHORIZATION="Api-Key invalid-key-12345")
        response = self.client.post(self.url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_post_with_empty_data(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {self.api_key}")
        response = self.client.post(self.url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_jwt_token_does_not_work(self):
        from core.tests.fixtures.users import create_regular_user

        user = create_regular_user(email="extupdate@test.com")
        self.authenticate_user(user)
        response = self.client.post(self.url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_malformed_insee_code_is_rejected(self):
        # Seule entrée libre non bornée de l'API externe : parcel_code est validé au
        # caractère près, insee_code ne l'était pas du tout.
        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {self.api_key}")

        for insee_code in ["", "34", "341720", "34A72", "x" * 300]:
            with self.subTest(insee_code=insee_code):
                response = self.client.post(
                    self.url,
                    {
                        "insee_code": insee_code,
                        "parcel_code": "AB1234",
                        "control_status": DetectionControlStatus.CONTROLLED_FIELD,
                    },
                    format="json",
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_corsican_insee_code_is_accepted(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {self.api_key}")

        serializer = UpdateControlStatusExternalApiInputSerializer(
            data={
                "insee_code": "2a004",
                "parcel_code": "AB1234",
                "control_status": DetectionControlStatus.CONTROLLED_FIELD,
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["insee_code"], "2A004")
