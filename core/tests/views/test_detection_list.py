import csv
import io
from unittest.mock import patch

from django.contrib.gis.geos import Point
from django.test import override_settings
from django.urls import reverse
from rest_framework import status

from core.constants.geo import SRID
from core.models.detection_data import DetectionControlStatus
from core.models.geo_custom_zone import GeoCustomZone
from core.models.tile_set import TileSetType
from core.tests.base import BaseAPITestCase
from core.tests.fixtures.users import (
    create_super_admin,
    create_regular_user,
    create_user_group,
    add_user_to_group,
)
from core.tests.fixtures.detection_data import (
    create_complete_detection_setup,
    create_detection,
    create_detection_data,
    create_detection_object,
    create_object_type,
    create_tile_set,
)
from core.tests.fixtures.geo_data import create_complete_geo_hierarchy


class DetectionListViewSetTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="dladmin@test.com")
        self.regular = create_regular_user(email="dluser@test.com")
        self.geo_data = create_complete_geo_hierarchy()
        self.detection_setup = create_complete_detection_setup(
            commune=self.geo_data["communes"]["montpellier"],
        )
        group = create_user_group(
            name="Test DL Group",
            geo_zones=[self.geo_data["departments"]["herault"]],
        )
        add_user_to_group(self.regular, group)
        add_user_to_group(self.super_admin, group)
        self.custom_zone = GeoCustomZone.objects.create(
            name="Zone DL",
            geometry=self.create_bbox_polygon(3.0, 43.0, 4.0, 44.0),
        )

    def test_list_unauthenticated(self):
        url = reverse("DetectionListViewSet-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_authenticated(self):
        self.authenticate_user(self.regular)
        url = reverse("DetectionListViewSet-list")
        response = self.client.get(
            url, {"customZonesUuids": str(self.custom_zone.uuid)}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_without_custom_zones_returns_400(self):
        self.authenticate_user(self.regular)
        url = reverse("DetectionListViewSet-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_accepts_the_supported_orderings(self):
        self.authenticate_user(self.regular)
        url = reverse("DetectionListViewSet-list")

        for ordering in [
            "score",
            "-score",
            "id",
            "-id",
            "parcel",
            "-parcel",
            "detectionControlStatus",
            "-detectionControlStatus",
        ]:
            with self.subTest(ordering=ordering):
                response = self.client.get(
                    url,
                    {
                        "customZonesUuids": str(self.custom_zone.uuid),
                        "ordering": ordering,
                    },
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_rejects_an_unsupported_ordering(self):
        # detectionsCount is the parcel table's own sort: detections have no such field.
        self.authenticate_user(self.regular)
        url = reverse("DetectionListViewSet-list")

        for ordering in ["detectionsCount", "-detectionsCount", "unknownField"]:
            with self.subTest(ordering=ordering):
                response = self.client.get(
                    url,
                    {
                        "customZonesUuids": str(self.custom_zone.uuid),
                        "ordering": ordering,
                    },
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn("ordering", response.data)


class DetectionListOrderingTests(BaseAPITestCase):
    """order_queryset sorts on one key (then id). OrderingFilter validates a comma list
    item by item, so "-score,id" is valid for the form but used to reach order_by() as
    one raw string: a FieldError, answered 500."""

    def setUp(self):
        super().setUp()
        geo = create_complete_geo_hierarchy()
        montpellier = geo["communes"]["montpellier"]
        object_type = create_object_type(name="Piscine tri")
        user = create_regular_user(email="dl-ordering@test.com")
        add_user_to_group(
            user, create_user_group(name="Ordering Group", geo_zones=[montpellier])
        )
        tile_set = create_tile_set(name="TS tri", tile_set_type=TileSetType.BACKGROUND)
        tile_set.geo_zones.set([montpellier])
        custom_zone = GeoCustomZone.objects.create(
            name="Zone tri",
            geometry=self.create_bbox_polygon(3.80, 43.55, 3.96, 43.67),
        )
        for x, score, control_status in [
            (3.87, 0.5, DetectionControlStatus.CONTROLLED_FIELD),
            (3.88, 0.9, DetectionControlStatus.NOT_CONTROLLED),
            (3.89, 0.7, DetectionControlStatus.PRIOR_LETTER_SENT),
        ]:
            detection = create_detection(
                detection_object=create_detection_object(
                    object_type=object_type, commune=montpellier
                ),
                tile_set=tile_set,
                geometry=Point(x, 43.61, srid=SRID),
                score=score,
                detection_data=create_detection_data(
                    detection_control_status=control_status
                ),
            )
            detection.detection_object.geo_custom_zones.add(custom_zone)

        self.params = {
            "objectTypesUuids": str(object_type.uuid),
            "customZonesUuids": str(custom_zone.uuid),
            "interfaceDrawn": "ALL",
        }
        self.authenticate_user(user)

    def _get(self, url_name, **params):
        return self.client.get(reverse(url_name), {**self.params, **params})

    def _csv_scores(self, response):
        rows = list(csv.reader(io.StringIO(response.content.decode())))
        return [row[6] for row in rows[1:]]

    def test_a_single_ordering_is_applied(self):
        for ordering in ["-score", "-score,"]:
            with self.subTest(ordering=ordering):
                response = self._get("DetectionListViewSet-list", ordering=ordering)

                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(
                    [item["score"] for item in response.data], [0.9, 0.7, 0.5]
                )

    def test_every_single_ordering_works_on_download_and_overview(self):
        for ordering in [
            "score",
            "-score",
            "id",
            "-id",
            "parcel",
            "-parcel",
            "detectionControlStatus",
            "-detectionControlStatus",
        ]:
            for output_format in ["csv", "xlsx"]:
                with self.subTest(ordering=ordering, output_format=output_format):
                    response = self._get(
                        "DetectionListViewSet-download",
                        ordering=ordering,
                        outputFormat=output_format,
                    )

                    self.assertEqual(response.status_code, status.HTTP_200_OK)

            with self.subTest(ordering=ordering, url_name="overview"):
                response = self._get(
                    "DetectionListViewSet-get-overview", ordering=ordering
                )

                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(response.json()["totalCount"], 3)

    def test_control_status_ordering_on_list_and_download(self):
        # The download's values_list() used to drop the annotation DISTINCT ON sorts on.
        for ordering, scores in [
            ("detectionControlStatus", [0.9, 0.5, 0.7]),
            ("-detectionControlStatus", [0.7, 0.5, 0.9]),
        ]:
            with self.subTest(ordering=ordering):
                listed = self._get("DetectionListViewSet-list", ordering=ordering)
                downloaded = self._get(
                    "DetectionListViewSet-download",
                    ordering=ordering,
                    outputFormat="csv",
                )

                self.assertEqual([item["score"] for item in listed.data], scores)
                self.assertEqual(downloaded.status_code, status.HTTP_200_OK)
                self.assertEqual(
                    self._csv_scores(downloaded),
                    ["{:.2f}".format(score * 100) for score in scores],
                )

    def test_a_comma_separated_ordering_is_refused(self):
        for url_name, params in [
            ("DetectionListViewSet-list", {}),
            ("DetectionListViewSet-download", {"outputFormat": "csv"}),
            ("DetectionListViewSet-get-overview", {}),
        ]:
            for ordering in ["-score,id", "parcel,-score", "detectionControlStatus,id"]:
                with self.subTest(url_name=url_name, ordering=ordering):
                    response = self._get(url_name, ordering=ordering, **params)

                    self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                    self.assertIn("ordering", response.data)


class DetectionListDownloadTests(BaseAPITestCase):
    """The export is capped at DOWNLOAD_LIMIT_ROWS detections. The frontend reads the
    row count and the truncation flag from the response headers to warn the user."""

    def setUp(self):
        super().setUp()
        geo = create_complete_geo_hierarchy()
        montpellier = geo["communes"]["montpellier"]
        self.object_type = create_object_type(name="Piscine export")
        self.user = create_regular_user(email="dl-export@test.com")
        add_user_to_group(
            self.user, create_user_group(name="Export Group", geo_zones=[montpellier])
        )
        tile_set = create_tile_set(
            name="TS export", tile_set_type=TileSetType.BACKGROUND
        )
        tile_set.geo_zones.set([montpellier])
        self.custom_zone = GeoCustomZone.objects.create(
            name="Zone export",
            geometry=self.create_bbox_polygon(3.80, 43.55, 3.96, 43.67),
        )
        for x in [3.87, 3.88, 3.89]:
            detection = create_detection(
                detection_object=create_detection_object(
                    object_type=self.object_type, commune=montpellier
                ),
                tile_set=tile_set,
                geometry=Point(x, 43.61, srid=SRID),
                detection_data=create_detection_data(),
            )
            detection.detection_object.geo_custom_zones.add(self.custom_zone)

        self.url = reverse("DetectionListViewSet-download")
        self.params = {
            "objectTypesUuids": str(self.object_type.uuid),
            "customZonesUuids": str(self.custom_zone.uuid),
            "interfaceDrawn": "ALL",
        }

    def _download(self, output_format="csv", **headers):
        self.authenticate_user(self.user)
        return self.client.get(
            self.url, {**self.params, "outputFormat": output_format}, **headers
        )

    def _csv_rows(self, response):
        return list(csv.reader(io.StringIO(response.content.decode())))[1:]

    def test_complete_export_carries_its_row_count(self):
        response = self._download()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(self._csv_rows(response)), 3)
        self.assertEqual(response["X-Export-Row-Count"], "3")
        self.assertEqual(response["X-Export-Truncated"], "false")

    def test_export_over_the_cap_is_flagged_truncated(self):
        with patch("core.views.detection.detection_list.DOWNLOAD_LIMIT_ROWS", 2):
            response = self._download()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(self._csv_rows(response)), 2)
        self.assertEqual(response["X-Export-Row-Count"], "2")
        self.assertEqual(response["X-Export-Truncated"], "true")

    def test_export_exactly_at_the_cap_is_not_truncated(self):
        with patch("core.views.detection.detection_list.DOWNLOAD_LIMIT_ROWS", 3):
            response = self._download()

        self.assertEqual(response["X-Export-Row-Count"], "3")
        self.assertEqual(response["X-Export-Truncated"], "false")

    def test_export_rejects_the_detections_count_ordering(self):
        self.authenticate_user(self.user)

        for ordering in ["detectionsCount", "-detectionsCount"]:
            with self.subTest(ordering=ordering):
                response = self.client.get(
                    self.url,
                    {**self.params, "outputFormat": "csv", "ordering": ordering},
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn("ordering", response.data)

    def test_xlsx_export_carries_the_headers(self):
        response = self._download("xlsx")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["X-Export-Row-Count"], "3")
        self.assertEqual(response["X-Export-Truncated"], "false")

    @override_settings(CORS_ALLOWED_ORIGINS=["https://aigle.example.org"])
    def test_headers_are_exposed_to_the_frontend_origin(self):
        response = self._download(HTTP_ORIGIN="https://aigle.example.org")

        exposed = {
            header.strip().lower()
            for header in response["Access-Control-Expose-Headers"].split(",")
        }
        self.assertIn("x-export-row-count", exposed)
        self.assertIn("x-export-truncated", exposed)
