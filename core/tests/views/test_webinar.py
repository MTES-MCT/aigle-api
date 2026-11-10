import datetime
import uuid

from django.urls import reverse
from rest_framework import status

from core.models.webinar import Webinar
from core.tests.base import BaseAPITestCase
from core.tests.fixtures.users import (
    create_admin,
    create_regular_user,
    create_super_admin,
)


def create_webinar(**kwargs) -> Webinar:
    return Webinar.objects.create(
        **{
            "title": "Webinaire produit",
            "date": datetime.date(2026, 11, 5),
            "start_time": datetime.time(14, 30),
            "end_time": datetime.time(15, 30),
            **kwargs,
        }
    )


class WebinarViewSetTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        # The migration seeds the webinars the frontend used to hard-code.
        Webinar.objects.all().delete()

        self.super_admin = create_super_admin(email="webinaradmin@test.com")
        self.admin = create_admin(email="webinaradmin2@test.com")
        self.regular = create_regular_user(email="webinaruser@test.com")
        self.webinar = create_webinar(
            title="Plan de contrôle",
            description="<p>Retours d’expérience</p>",
            visio_url="https://visio.numerique.gouv.fr/abc",
        )
        self.past_webinar = create_webinar(
            title="Utiliser AIGLE sur le terrain",
            date=datetime.date(2026, 6, 18),
            start_time=None,
            end_time=None,
            replay_url="https://tube.numerique.gouv.fr/w/pb3BaDvYGbAP3b9zUZghZ3",
        )

        self.list_url = reverse("WebinarViewSet-list")

    def detail_url(self, webinar_uuid) -> str:
        return reverse("WebinarViewSet-detail", kwargs={"uuid": str(webinar_uuid)})

    def test_list_unauthenticated(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_authenticated(self):
        self.authenticate_user(self.regular)
        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [webinar["title"] for webinar in response.data],
            ["Plan de contrôle", "Utiliser AIGLE sur le terrain"],
        )
        first = response.data[0]
        self.assertEqual(first["date"], "2026-11-05")
        self.assertEqual(first["start_time"], "14:30")
        self.assertEqual(first["end_time"], "15:30")
        self.assertEqual(first["visio_url"], "https://visio.numerique.gouv.fr/abc")
        self.assertIsNone(response.data[1]["start_time"])

    def test_list_hides_deleted(self):
        self.webinar.deleted = True
        self.webinar.save()
        self.authenticate_user(self.regular)

        response = self.client.get(self.list_url)

        self.assertEqual(
            [webinar["title"] for webinar in response.data],
            ["Utiliser AIGLE sur le terrain"],
        )

    def test_search_by_title(self):
        self.authenticate_user(self.super_admin)
        response = self.client.get(self.list_url, {"q": "terrain"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [webinar["title"] for webinar in response.data],
            ["Utiliser AIGLE sur le terrain"],
        )

    def test_retrieve(self):
        self.authenticate_user(self.regular)
        response = self.client.get(self.detail_url(self.webinar.uuid))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["title"], "Plan de contrôle")

    def test_retrieve_nonexistent_returns_404(self):
        self.authenticate_user(self.regular)
        response = self.client.get(self.detail_url(uuid.uuid4()))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_create_as_regular_forbidden(self):
        self.authenticate_user(self.regular)
        response = self.client.post(
            self.list_url, {"title": "x", "date": "2026-12-01"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_as_admin_forbidden(self):
        self.authenticate_user(self.admin)
        response = self.client.post(
            self.list_url, {"title": "x", "date": "2026-12-01"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_as_super_admin(self):
        self.authenticate_user(self.super_admin)
        response = self.client.post(
            self.list_url,
            {
                "title": "Nouveautés",
                "description": "<p>Les <strong>nouveautés</strong></p>",
                "date": "2026-12-01",
                "startTime": "10:00",
                "endTime": "11:00",
                "registrationUrl": "https://example.org/inscription",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("uuid", response.data)
        self.assertEqual(response.data["start_time"], "10:00")
        webinar = Webinar.objects.get(uuid=response.data["uuid"])
        self.assertEqual(webinar.end_time, datetime.time(11, 0))
        self.assertEqual(webinar.registration_url, "https://example.org/inscription")
        self.assertIsNone(webinar.replay_url)

    def test_create_sanitizes_description(self):
        self.authenticate_user(self.super_admin)
        response = self.client.post(
            self.list_url,
            {
                "title": "Nouveautés",
                "description": '<p onclick="x()">Voir <a href="javascript:alert(1)">ici</a>'
                '<a href="https://aigle.beta.gouv.fr">là</a></p><script>alert(1)</script>',
                "date": "2026-12-01",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            response.data["description"],
            '<p>Voir <a target="_blank" rel="noopener noreferrer">ici</a>'
            '<a href="https://aigle.beta.gouv.fr" target="_blank" rel="noopener noreferrer">là</a></p>',
        )

    def test_create_empty_editor_stores_empty_description(self):
        self.authenticate_user(self.super_admin)
        response = self.client.post(
            self.list_url,
            {"title": "Nouveautés", "description": "<p></p>", "date": "2026-12-01"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["description"], "")

    def test_create_with_only_start_time_rejected(self):
        self.authenticate_user(self.super_admin)
        response = self.client.post(
            self.list_url,
            {"title": "x", "date": "2026-12-01", "startTime": "10:00"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("end_time", response.data)

    def test_create_with_end_before_start_rejected(self):
        self.authenticate_user(self.super_admin)
        response = self.client.post(
            self.list_url,
            {
                "title": "x",
                "date": "2026-12-01",
                "startTime": "11:00",
                "endTime": "10:00",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("end_time", response.data)

    def test_create_with_invalid_url_rejected(self):
        self.authenticate_user(self.super_admin)
        response = self.client.post(
            self.list_url,
            {"title": "x", "date": "2026-12-01", "visioUrl": "pas une url"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("visio_url", response.data)

    def test_partial_update_keeps_stored_time_slot(self):
        self.authenticate_user(self.super_admin)
        response = self.client.patch(
            self.detail_url(self.webinar.uuid),
            {"endTime": "16:00", "replayUrl": "https://tube.numerique.gouv.fr/w/abc"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.webinar.refresh_from_db()
        self.assertEqual(self.webinar.start_time, datetime.time(14, 30))
        self.assertEqual(self.webinar.end_time, datetime.time(16, 0))
        self.assertEqual(
            self.webinar.replay_url, "https://tube.numerique.gouv.fr/w/abc"
        )

    def test_partial_update_clears_time_slot(self):
        self.authenticate_user(self.super_admin)
        response = self.client.patch(
            self.detail_url(self.webinar.uuid),
            {"startTime": None, "endTime": None, "visioUrl": None},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.webinar.refresh_from_db()
        self.assertIsNone(self.webinar.start_time)
        self.assertIsNone(self.webinar.end_time)
        self.assertIsNone(self.webinar.visio_url)

    def test_update_as_regular_forbidden(self):
        self.authenticate_user(self.regular)
        response = self.client.patch(
            self.detail_url(self.webinar.uuid), {"title": "x"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_as_super_admin_is_soft(self):
        self.authenticate_user(self.super_admin)
        response = self.client.delete(self.detail_url(self.webinar.uuid))

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.webinar.refresh_from_db()
        self.assertTrue(self.webinar.deleted)
        self.assertEqual(
            self.client.get(self.detail_url(self.webinar.uuid)).status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_delete_as_regular_forbidden(self):
        self.authenticate_user(self.regular)
        response = self.client.delete(self.detail_url(self.webinar.uuid))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.webinar.refresh_from_db()
        self.assertFalse(self.webinar.deleted)


class WebinarSeedTests(BaseAPITestCase):
    def test_migration_seeds_former_frontend_webinars(self):
        self.assertEqual(
            list(Webinar.objects.order_by("-date").values_list("title", flat=True)),
            [
                "Comment construire et suivre un plan de contrôle sur AIGLE ?",
                "Webinaire produit : les nouveautés d’AIGLE",
                "Webinaire « Utiliser AIGLE sur le terrain »",
                "Webinaire produit AIGLE",
            ],
        )
