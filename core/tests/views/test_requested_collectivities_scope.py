"""Collectivities passed as filters (communesUuids, epcisUuids, departmentsUuids,
regionsUuids) are cut down to the caller's territory.

The tile set of these tests is attached to the whole region, as imagery often is: the
tile-set filter alone would then let a Montpellier agent read Nîmes by asking for it.
"""

from django.contrib.gis.geos import Point
from django.urls import reverse
from rest_framework import status

from core.constants.geo import SRID
from core.models.detection_data import (
    DetectionControlStatus,
    DetectionValidationStatus,
)
from core.models.geo_custom_zone import GeoCustomZone
from core.permissions.scope import HEADER_NAME
from core.tests.base import BaseAPITestCase
from core.tests.fixtures.detection_data import (
    create_detection,
    create_detection_data,
    create_detection_object,
    create_object_type_with_category,
    create_tile_set,
)
from core.tests.fixtures.geo_data import create_complete_geo_hierarchy, create_parcel
from core.tests.fixtures.users import (
    add_user_to_group,
    create_regular_user,
    create_super_admin,
    create_user_group,
)


class RequestedCollectivitiesScopeTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        geo = create_complete_geo_hierarchy()
        self.communes = geo["communes"]
        self.herault = geo["departments"]["herault"]
        self.occitanie = geo["regions"]["occitanie"]

        tile_set = create_tile_set(name="Occitanie 2024")
        tile_set.geo_zones.add(self.occitanie)

        self.object_type, category = create_object_type_with_category(
            object_type_name="Cabane scope", category_name="Cabanisation scope"
        )
        self.zone = GeoCustomZone.objects.create(
            name="Zone scope",
            geometry=self.create_bbox_polygon(3.0, 43.0, 5.0, 45.0),
        )

        self.detections = {
            name: self._detection(self.communes[name], tile_set, index)
            for index, name in enumerate(["montpellier", "beziers", "nimes"])
        }

        self.commune_group = create_user_group(
            name="Mairie de Montpellier", geo_zones=[self.communes["montpellier"]]
        )
        self.ddtm_group = create_user_group(name="DDTM 34", geo_zones=[self.herault])
        for group in (self.commune_group, self.ddtm_group):
            group.object_type_categories.add(category)
            group.geo_custom_zones.add(self.zone)

        self.commune_user = create_regular_user(email="scope-commune@test.com")
        add_user_to_group(self.commune_user, self.commune_group)
        self.ddtm_user = create_regular_user(email="scope-ddtm@test.com")
        add_user_to_group(self.ddtm_user, self.ddtm_group)
        self.super_admin = create_super_admin(email="scope-admin@test.com")

    def _detection(self, commune, tile_set, index):
        lon, lat = commune.geometry.centroid.coords
        parcel = create_parcel(
            commune=commune,
            id_parcellaire=f"{commune.iso_code}0AB{index:04d}",
            x=lon,
            y=lat,
        )
        detection_object = create_detection_object(
            object_type=self.object_type, parcel=parcel, commune=commune
        )
        detection_object.geo_custom_zones.add(self.zone)
        return create_detection(
            detection_object=detection_object,
            tile_set=tile_set,
            geometry=Point(lon, lat, srid=SRID),
            detection_data=create_detection_data(
                detection_control_status=DetectionControlStatus.NOT_CONTROLLED,
                detection_validation_status=DetectionValidationStatus.SUSPECT,
            ),
        )

    def _list_detections(self, **params):
        return self.client.get(
            reverse("DetectionListViewSet-list"),
            {
                "customZonesUuids": str(self.zone.uuid),
                "objectTypesUuids": str(self.object_type.uuid),
                **params,
            },
        )

    @staticmethod
    def _rows(response):
        # paginated only when a limit is passed
        return (
            response.data["results"]
            if isinstance(response.data, dict)
            else response.data
        )

    def _listed_communes(self, response):
        uuids = {row["uuid"] for row in self._rows(response)}
        return {
            name
            for name, detection in self.detections.items()
            if str(detection.uuid) in uuids
        }

    def test_a_commune_agent_cannot_read_another_commune(self):
        self.authenticate_user(self.commune_user)

        for name in ("beziers", "nimes"):
            response = self._list_detections(
                communesUuids=str(self.communes[name].uuid)
            )
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, name)

    def test_a_commune_agent_reads_its_own_commune(self):
        self.authenticate_user(self.commune_user)

        response = self._list_detections(
            communesUuids=str(self.communes["montpellier"].uuid)
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._listed_communes(response), {"montpellier"})

    def test_a_mixed_request_is_cut_down_to_the_territory(self):
        self.authenticate_user(self.commune_user)

        response = self._list_detections(
            communesUuids=f"{self.communes['montpellier'].uuid},{self.communes['nimes'].uuid}"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._listed_communes(response), {"montpellier"})

    def test_asking_for_the_department_or_the_region_does_not_widen_the_territory(self):
        self.authenticate_user(self.commune_user)

        for params in (
            {"departmentsUuids": str(self.herault.uuid)},
            {"regionsUuids": str(self.occitanie.uuid)},
        ):
            response = self._list_detections(**params)
            self.assertEqual(response.status_code, status.HTTP_200_OK, params)
            self.assertEqual(self._listed_communes(response), {"montpellier"}, params)

    def test_a_ddtm_reads_the_communes_of_its_department_only(self):
        self.authenticate_user(self.ddtm_user)

        response = self._list_detections(departmentsUuids=str(self.herault.uuid))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._listed_communes(response), {"montpellier", "beziers"})

        response = self._list_detections(
            communesUuids=str(self.communes["beziers"].uuid)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._listed_communes(response), {"beziers"})

        response = self._list_detections(communesUuids=str(self.communes["nimes"].uuid))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_an_unscoped_super_admin_stays_unrestricted(self):
        self.authenticate_user(self.super_admin)

        response = self._list_detections(communesUuids=str(self.communes["nimes"].uuid))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._listed_communes(response), {"nimes"})

    def test_an_impersonating_super_admin_is_held_to_the_group_territory(self):
        self.authenticate_user(self.super_admin)

        response = self.client.get(
            reverse("DetectionListViewSet-list"),
            {
                "customZonesUuids": str(self.zone.uuid),
                "objectTypesUuids": str(self.object_type.uuid),
                "communesUuids": str(self.communes["nimes"].uuid),
            },
            **{HEADER_NAME: str(self.commune_group.uuid)},
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_the_parcel_table_is_held_to_the_territory_too(self):
        self.authenticate_user(self.commune_user)
        url = reverse("ParcelViewSet-list-items")
        params = {
            "customZonesUuids": str(self.zone.uuid),
            "objectTypesUuids": str(self.object_type.uuid),
            # what the frontend always sends
            "interfaceDrawn": "ALL",
        }

        response = self.client.get(
            url, {**params, "communesUuids": str(self.communes["nimes"].uuid)}
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        response = self.client.get(
            url,
            {
                **params,
                "communesUuids": f"{self.communes['montpellier'].uuid},{self.communes['nimes'].uuid}",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            {row["commune"]["name"] for row in self._rows(response)},
            {self.communes["montpellier"].name},
        )
