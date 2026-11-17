import datetime
import uuid

from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from core.models.detection_type_overlap_report import (
    DetectionTypeOverlapReport,
    DetectionTypeOverlapReportObjectType,
)
from core.models.geo_department import GeoDepartment
from core.models.geo_region import GeoRegion
from core.tests.base import BaseAPITestCase
from core.tests.fixtures.detection_data import create_object_type, create_tile_set
from core.tests.fixtures.users import (
    create_admin,
    create_regular_user,
    create_super_admin,
)


class DetectionTypeOverlapReportViewSetTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="overlap-admin@test.com")
        region = GeoRegion.objects.create(
            name="Occitanie", insee_code="76", surface_km2=1
        )
        self.herault = GeoDepartment.objects.create(
            name="Hérault", insee_code="34", surface_km2=1, region=region
        )
        self.gard = GeoDepartment.objects.create(
            name="Gard", insee_code="30", surface_km2=1, region=region
        )
        self.hard = create_object_type(
            name="Construction en dur", prescription_duration_years=6
        )
        self.pool = create_object_type(name="Piscine", prescription_duration_years=6)
        self.tile_set = create_tile_set(
            name="Hérault (34) 2024", date=datetime.date(2024, 1, 1)
        )

        self.herault_report = self._report(self.herault, days_ago=1)
        self.herault_report.tile_sets.add(self.tile_set)
        DetectionTypeOverlapReportObjectType.objects.bulk_create(
            [
                DetectionTypeOverlapReportObjectType(
                    report=self.herault_report,
                    object_type=self.pool,
                    overlapping_count=4,
                    custom_zones_overlapping_count=1,
                ),
                DetectionTypeOverlapReportObjectType(
                    report=self.herault_report,
                    object_type=self.hard,
                    overlapping_count=10,
                    custom_zones_overlapping_count=2,
                ),
            ]
        )
        self.gard_report = self._report(self.gard, days_ago=0)

    def _report(self, geo_zone, days_ago):
        return DetectionTypeOverlapReport.objects.create(
            geo_zone=geo_zone,
            report_date=timezone.now() - datetime.timedelta(days=days_ago),
            detections_count=100,
            overlapping_count=20,
            overlapping_prescribable_count=11,
            custom_zones_detections_count=40,
            custom_zones_overlapping_count=8,
            custom_zones_overlapping_prescribable_count=3,
        )

    def _list(self, **params):
        # the admin table always paginates
        return self.client.get(
            reverse("DetectionTypeOverlapReportViewSet-list"), {"limit": 10, **params}
        )

    def _detail_url(self, report_uuid):
        return reverse(
            "DetectionTypeOverlapReportViewSet-detail", kwargs={"uuid": report_uuid}
        )

    def test_list_most_recent_first(self):
        self.authenticate_user(self.super_admin)
        response = self._list()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual(
            [result["geoZone"]["name"] for result in results], ["Gard", "Hérault"]
        )
        herault = results[1]
        self.assertEqual(herault["geoZone"]["code"], "34")
        self.assertEqual(herault["geoZone"]["geoZoneType"], "DEPARTMENT")
        self.assertEqual(
            [tile_set["name"] for tile_set in herault["tileSets"]],
            ["Hérault (34) 2024"],
        )
        self.assertEqual(herault["overlappingPrescribableCount"], 11)
        self.assertEqual(herault["customZonesDetectionsCount"], 40)
        # ordered by object type name
        self.assertEqual(
            [
                (item["objectType"]["name"], item["overlappingCount"])
                for item in herault["objectTypes"]
            ],
            [("Construction en dur", 10), ("Piscine", 4)],
        )

    def test_list_unauthenticated(self):
        response = self._list()
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_as_admin_forbidden(self):
        self.authenticate_user(create_admin(email="overlap-mod@test.com"))
        response = self._list()
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_as_regular_forbidden(self):
        self.authenticate_user(create_regular_user(email="overlap-user@test.com"))
        response = self._list()
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_search(self):
        self.authenticate_user(self.super_admin)
        response = self._list(q="herau")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [result["uuid"] for result in response.json()["results"]],
            [str(self.herault_report.uuid)],
        )

    def test_filter_by_geo_zone(self):
        self.authenticate_user(self.super_admin)
        response = self._list(geoZoneUuid=str(self.gard.uuid))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [result["uuid"] for result in response.json()["results"]],
            [str(self.gard_report.uuid)],
        )

    def test_retrieve(self):
        self.authenticate_user(self.super_admin)
        response = self.client.get(self._detail_url(self.herault_report.uuid))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["geoZone"]["uuid"], str(self.herault.uuid))
        self.assertEqual(len(response.json()["objectTypes"]), 2)

    def test_retrieve_nonexistent(self):
        self.authenticate_user(self.super_admin)
        response = self.client.get(self._detail_url(uuid.uuid4()))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_read_only(self):
        self.authenticate_user(self.super_admin)
        response = self.client.delete(self._detail_url(self.herault_report.uuid))
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
