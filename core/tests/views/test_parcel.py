from django.contrib.gis.geos import Point
from django.urls import reverse
from rest_framework import status

from core.models.detection_data import (
    DetectionControlStatus,
    DetectionValidationStatus,
)
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
