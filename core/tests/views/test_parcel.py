from datetime import date
from unittest import mock

from dateutil.relativedelta import relativedelta
from django.contrib.gis.geos import Point
from django.urls import reverse
from rest_framework import status

from core.models.detection_data import (
    DetectionControlStatus,
    DetectionPrescriptionStatus,
    DetectionValidationStatus,
)
from core.services.prescription import PrescriptionService
from core.models.geo_custom_zone import GeoCustomZone, GeoCustomZoneStatus
from core.models.geo_sub_custom_zone import GeoSubCustomZone
from core.tests.base import BaseAPITestCase
from core.tests.fixtures.detection_data import (
    create_detection,
    create_detection_data,
    create_detection_object,
    create_object_type,
    create_tile_set,
)
from core.tests.fixtures.users import (
    create_super_admin,
    create_regular_user,
    create_user_group,
    add_user_to_group,
)
from core.tests.fixtures.geo_data import create_complete_geo_hierarchy


class ParcelViewSetTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="parcadmin@test.com")
        self.regular = create_regular_user(email="parcuser@test.com")
        self.geo_data = create_complete_geo_hierarchy()
        self.parcels = self.geo_data["parcels"]
        group = create_user_group(
            name="Test Parcel Group",
            geo_zones=[self.geo_data["departments"]["herault"]],
        )
        add_user_to_group(self.regular, group)
        add_user_to_group(self.super_admin, group)

    def test_list_authenticated(self):
        self.authenticate_user(self.regular)
        url = reverse("ParcelViewSet-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_unauthenticated(self):
        url = reverse("ParcelViewSet-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_retrieve(self):
        self.authenticate_user(self.regular)
        parcel = self.parcels[0]
        url = reverse("ParcelViewSet-detail", kwargs={"uuid": str(parcel.uuid)})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def _attach_reportable_detection(self, parcel):
        """A detection on `parcel` that survives every get_parcel_detail filter, so the
        parcel comes back with its associated custom zones populated."""
        object_type = create_object_type(name="Cabane")
        detection_object = create_detection_object(
            object_type=object_type, parcel=parcel, commune=parcel.commune
        )
        detection_data = create_detection_data(
            detection_validation_status=DetectionValidationStatus.DETECTED_NOT_VERIFIED,
            detection_control_status=DetectionControlStatus.NOT_CONTROLLED,
        )
        create_detection(
            detection_object=detection_object,
            tile_set=create_tile_set(name="TS download infos"),
            geometry=Point(3.88, 43.61, srid=4326),
            score=0.95,
            detection_data=detection_data,
        )
        return detection_object

    def test_download_infos_excludes_deactivated_custom_zones(self):
        # Regression: the signalement report ("Fiche de signalement") listed deactivated
        # zones à enjeux. get_download_infos must only report ACTIVE custom zones.
        self.authenticate_user(self.super_admin)
        parcel = self.parcels[0]
        detection_object = self._attach_reportable_detection(parcel)

        zone_geometry = self.create_bbox_polygon(3.86, 43.59, 3.90, 43.63)
        active_zone = GeoCustomZone.objects.create(
            name="Active enjeux",
            geometry=zone_geometry,
            geo_custom_zone_status=GeoCustomZoneStatus.ACTIVE,
        )
        inactive_zone = GeoCustomZone.objects.create(
            name="Deactivated enjeux",
            geometry=zone_geometry,
            geo_custom_zone_status=GeoCustomZoneStatus.INACTIVE,
        )
        # a sub zone of the deactivated parent must not leak either
        inactive_sub_zone = GeoSubCustomZone.objects.create(
            name="Deactivated sub", custom_zone=inactive_zone, geometry=zone_geometry
        )
        detection_object.geo_custom_zones.add(active_zone, inactive_zone)
        detection_object.geo_sub_custom_zones.add(inactive_sub_zone)

        url = reverse(
            "ParcelViewSet-get-download-infos", kwargs={"uuid": str(parcel.uuid)}
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        custom_zones = response.json()["customGeoZones"]
        zone_names = {zone["name"] for zone in custom_zones}
        self.assertIn("Active enjeux", zone_names)
        self.assertNotIn("Deactivated enjeux", zone_names)

        sub_zone_names = {
            sub["name"] for zone in custom_zones for sub in zone["subCustomZones"]
        }
        self.assertNotIn("Deactivated sub", sub_zone_names)

    def test_commune_envelope_is_geojson_bbox(self):
        # Envelope is computed in PostGIS to avoid loading the heavy deferred
        # commune geometry into Python.
        #
        # Import core.urls first: importing the serializer directly trips a
        # serializer import cycle (URLconf load resolves the graph in app order).
        import core.urls  # noqa: F401
        from core.serializers.parcel import ParcelDetailSerializer

        parcel = self.parcels[0]
        self.assertIsNotNone(parcel.commune_id)

        envelope = ParcelDetailSerializer().get_commune_envelope(parcel)
        self.assertIsNotNone(envelope)
        self.assertEqual(envelope["type"], "Polygon")
        self.assertGreater(len(envelope["coordinates"][0]), 0)


class ParcelDownloadInfosSignalementTests(BaseAPITestCase):
    """The signalement report ("Fiche de signalement") header and its aerial previews must
    describe the same objects: everything counted has to be drawable on a previewed tile set,
    and a prescribed (time-barred) object must not reach the report at all."""

    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="signalement@test.com")
        self.authenticate_user(self.super_admin)
        self.geo_data = create_complete_geo_hierarchy()
        self.parcel = self.geo_data["parcels"][0]
        self.commune = self.geo_data["communes"]["montpellier"]
        add_user_to_group(
            self.super_admin,
            create_user_group(
                name="Signalement Group",
                geo_zones=[self.geo_data["departments"]["herault"]],
            ),
        )
        self.active_zone = GeoCustomZone.objects.create(
            name="Signalement enjeux",
            geometry=self.create_bbox_polygon(3.86, 43.59, 3.90, 43.63),
            geo_custom_zone_status=GeoCustomZoneStatus.ACTIVE,
        )
        # get_previews keeps the newest, the runner-up and the newest one at least 6 years
        # old, so the -10y tile set is always the one left out whatever today's date is
        self.tile_sets = {
            years_ago: self._create_zoned_tile_set(years_ago)
            for years_ago in [10, 7, 4, 1]
        }

    def _create_zoned_tile_set(self, years_ago: int):
        tile_set = create_tile_set(
            name=f"Signalement TS -{years_ago}y",
            date=date.today() - relativedelta(years=years_ago),
        )
        # get_previews only keeps tile sets whose geo zones intersect the parcel
        tile_set.geo_zones.add(self.commune)
        return tile_set

    def _create_object(self, name, years_ago_list, object_type=None):
        object_type = object_type or create_object_type(name=name)
        detection_object = create_detection_object(
            object_type=object_type, parcel=self.parcel, commune=self.commune
        )
        # the object filter requires an active zone à enjeux, as on every detection surface
        detection_object.geo_custom_zones.add(self.active_zone)

        for years_ago in years_ago_list:
            create_detection(
                detection_object=detection_object,
                tile_set=self.tile_sets[years_ago],
                geometry=Point(3.88, 43.61, srid=4326),
                score=0.95,
                detection_data=create_detection_data(
                    detection_validation_status=DetectionValidationStatus.DETECTED_NOT_VERIFIED,
                    detection_control_status=DetectionControlStatus.NOT_CONTROLLED,
                ),
            )

        return detection_object

    def _download_infos(self):
        url = reverse(
            "ParcelViewSet-get-download-infos", kwargs={"uuid": str(self.parcel.uuid)}
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    def test_object_detected_only_on_a_non_previewed_tile_set_is_not_reported(self):
        # Regression: the header printed "Camping car : 1" for an object whose only detection
        # sits on a year the report never renders, so it could not be drawn anywhere.
        self._create_object("Construction en dur", [1])
        self._create_object("Camping car", [10])

        body = self._download_infos()

        previewed_uuids = {
            preview["tileSet"]["uuid"] for preview in body["tileSetPreviews"]
        }
        self.assertNotIn(str(self.tile_sets[10].uuid), previewed_uuids)

        reported_types = {obj["objectType"]["name"] for obj in body["detectionObjects"]}
        self.assertIn("Construction en dur", reported_types)
        self.assertNotIn("Camping car", reported_types)

    def test_every_reported_object_is_drawable_on_a_preview(self):
        self._create_object("Construction en dur", [7, 4, 1])
        self._create_object("Camping car", [10])

        body = self._download_infos()

        previewed_uuids = {
            preview["tileSet"]["uuid"] for preview in body["tileSetPreviews"]
        }
        self.assertTrue(body["detectionObjects"])

        for detection_object in body["detectionObjects"]:
            detection_tile_sets = {
                detection["tileSet"]["uuid"]
                for detection in detection_object["detections"]
            }
            self.assertTrue(detection_tile_sets)
            # nothing outside the previews may be served: it would be counted, never drawn
            self.assertFalse(detection_tile_sets - previewed_uuids)

    def test_prescribed_object_is_not_reported(self):
        # Regression: a prescribed object survived the report because prescription is written
        # per detection and its oldest one is never prescribed.
        prescribed_type = create_object_type(
            name="Construction prescrite", prescription_duration_years=6
        )
        prescribed = self._create_object(
            "Construction prescrite", [7, 1], object_type=prescribed_type
        )
        self._create_object("Construction en dur", [7, 1])

        PrescriptionService.compute_prescription(detection_object=prescribed)

        prescription_statuses = {
            detection.detection_data.detection_prescription_status
            for detection in prescribed.detections.select_related("detection_data")
        }
        self.assertIn(DetectionPrescriptionStatus.PRESCRIBED, prescription_statuses)

        body = self._download_infos()

        reported_types = {obj["objectType"]["name"] for obj in body["detectionObjects"]}
        self.assertIn("Construction en dur", reported_types)
        self.assertNotIn("Construction prescrite", reported_types)

    def test_object_with_an_official_report_is_reported_despite_prescribed_siblings(
        self,
    ):
        # Regression: a procès-verbal interrupts prescription, but set_detection_control_status
        # un-prescribes only the row it is drawn on. Judging the object on "any prescribed
        # detection" hid exactly the objects the DDTM had formally acted on.
        object_type = create_object_type(
            name="Construction avec PV", prescription_duration_years=6
        )
        detection_object = self._create_object(
            "Construction avec PV", [10, 7, 4, 1], object_type=object_type
        )
        PrescriptionService.compute_prescription(detection_object=detection_object)

        latest = detection_object.detections.order_by("-tile_set__date").first()
        latest.detection_data.set_detection_control_status(
            DetectionControlStatus.OFFICIAL_REPORT_DRAWN_UP
        )
        latest.detection_data.save()

        older_statuses = {
            detection.detection_data.detection_prescription_status
            for detection in detection_object.detections.select_related(
                "detection_data"
            ).exclude(pk=latest.pk)
        }
        self.assertIn(DetectionPrescriptionStatus.PRESCRIBED, older_statuses)

        body = self._download_infos()

        self.assertIn(
            "Construction avec PV",
            {obj["objectType"]["name"] for obj in body["detectionObjects"]},
        )

    def test_reported_object_carries_only_its_previewed_detections(self):
        # the header counts objects, the images draw detections: an object present on both a
        # previewed and a non-previewed year must not ship the year that cannot be drawn
        self._create_object("Construction en dur", [10, 7, 4, 1])

        body = self._download_infos()

        previewed_uuids = {
            preview["tileSet"]["uuid"] for preview in body["tileSetPreviews"]
        }
        detection_tile_sets = {
            detection["tileSet"]["uuid"]
            for obj in body["detectionObjects"]
            for detection in obj["detections"]
        }
        self.assertEqual(detection_tile_sets, previewed_uuids)
        self.assertNotIn(str(self.tile_sets[10].uuid), detection_tile_sets)

    def test_parcel_with_only_prescribed_objects_reports_nothing(self):
        prescribed_type = create_object_type(
            name="Cabane prescrite", prescription_duration_years=6
        )
        prescribed = self._create_object(
            "Cabane prescrite", [7, 1], object_type=prescribed_type
        )
        PrescriptionService.compute_prescription(detection_object=prescribed)

        # a geometry-less payload is what the frontend reads as "aucune détection à signaler"
        body = self._download_infos()
        self.assertIsNone(body["geometry"])
        self.assertEqual(body["detectionObjects"], [])

    def test_jugement_control_status_is_reported(self):
        detection_object = create_detection_object(
            object_type=create_object_type(name="Construction jugee"),
            parcel=self.parcel,
            commune=self.commune,
        )
        detection_object.geo_custom_zones.add(self.active_zone)
        create_detection(
            detection_object=detection_object,
            tile_set=self.tile_sets[1],
            geometry=Point(3.88, 43.61, srid=4326),
            score=0.95,
            detection_data=create_detection_data(
                detection_validation_status=DetectionValidationStatus.SUSPECT,
                detection_control_status=DetectionControlStatus.JUGEMENT,
            ),
        )

        body = self._download_infos()

        self.assertIn(
            "Construction jugee",
            {obj["objectType"]["name"] for obj in body["detectionObjects"]},
        )

    def test_download_infos_unauthenticated(self):
        self.client.credentials()
        url = reverse(
            "ParcelViewSet-get-download-infos", kwargs={"uuid": str(self.parcel.uuid)}
        )
        self.assertEqual(self.client.get(url).status_code, status.HTTP_401_UNAUTHORIZED)


class PrescriptionInvariantTests(BaseAPITestCase):
    def test_oldest_detection_is_never_auto_prescribed(self):
        # every "is this object prescribed" predicate depends on this: the anchor detection
        # carries no status, so a per-detection test can never reject a prescribed object
        object_type = create_object_type(
            name="Cabane prescriptible", prescription_duration_years=6
        )
        detection_object = create_detection_object(object_type=object_type)

        for years_ago in [10, 1]:
            create_detection(
                detection_object=detection_object,
                tile_set=create_tile_set(
                    name=f"Prescription TS -{years_ago}y",
                    date=date.today() - relativedelta(years=years_ago),
                ),
                detection_data=create_detection_data(),
            )

        PrescriptionService.compute_prescription(detection_object=detection_object)

        detections = sorted(
            detection_object.detections.select_related(
                "detection_data", "tile_set"
            ).all(),
            key=lambda detection: detection.tile_set.date,
        )
        self.assertIsNone(detections[0].detection_data.detection_prescription_status)
        self.assertEqual(
            detections[-1].detection_data.detection_prescription_status,
            DetectionPrescriptionStatus.PRESCRIBED,
        )

    def test_get_tile_set_years_ago_handles_leap_day(self):
        # date.replace(year=year - 6) raises on 29 February: the target year is never a leap
        # year. Both clocks are pinned: reading the real one on either side makes this vacuous
        # every day but one, and pinning only the function's makes it fail from 2030 on.
        import core.permissions.tile_set as tile_set_module
        from core.permissions.tile_set import get_tile_set_years_ago

        tile_set = create_tile_set(name="Leap day TS", date=date(2018, 1, 1))

        with mock.patch.object(tile_set_module, "date_type") as date_type_mock:
            date_type_mock.today.return_value = date(2028, 2, 29)
            self.assertEqual(
                get_tile_set_years_ago(tile_sets=[tile_set], relative_years=6), tile_set
            )
