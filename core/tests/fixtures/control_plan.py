"""A DDTM group of the Hérault with the PLAN_DE_CONTROLE flag, two imagery years and two
zones à enjeux, to exercise the control plans."""

from datetime import date

from django.contrib.gis.geos import Point

from core.constants.geo import SRID
from core.models.detection import DetectionSource
from core.models.detection_data import (
    DetectionControlStatus,
    DetectionValidationStatus,
)
from core.models.geo_custom_zone import GeoCustomZone
from core.models.geo_custom_zone_category import GeoCustomZoneCategory
from core.models.object_type_category import (
    ObjectTypeCategoryObjectType,
    ObjectTypeCategoryObjectTypeStatus,
)
from core.models.user_group import FeatureFlag, UserGroupRight, UserUserGroup
from core.tests.base import BaseAPITestCase
from core.tests.fixtures.detection_data import (
    create_detection,
    create_detection_data,
    create_detection_object,
    create_object_type,
    create_object_type_with_category,
    create_tile_set,
)
from core.tests.fixtures.geo_data import create_complete_geo_hierarchy, create_parcel
from core.tests.fixtures.users import (
    add_user_to_group,
    create_regular_user,
    create_user_group,
)

PLAN_URL = "/api/control-plan/"
WAVE_URL = "/api/control-plan-wave/"
PARCEL_URL = "/api/control-plan-parcel/"


class ControlPlanTestCase(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        geo = create_complete_geo_hierarchy()
        self.herault = geo["departments"]["herault"]
        self.montpellier = geo["communes"]["montpellier"]
        self.beziers = geo["communes"]["beziers"]
        self.nimes = geo["communes"]["nimes"]

        self.ts_2021 = create_tile_set(name="Hérault 2021", date=date(2021, 6, 1))
        self.ts_2024 = create_tile_set(name="Hérault 2024", date=date(2024, 6, 1))
        for tile_set in (self.ts_2021, self.ts_2024):
            tile_set.geo_zones.add(self.herault)

        self.cabane, self.category = create_object_type_with_category(
            object_type_name="Cabane plan", category_name="Cabanisation plan"
        )
        self.piscine = create_object_type(name="Piscine plan")
        ObjectTypeCategoryObjectType.objects.create(
            object_type_category=self.category,
            object_type=self.piscine,
            object_type_category_object_type_status=ObjectTypeCategoryObjectTypeStatus.VISIBLE,
        )

        zone_category = GeoCustomZoneCategory.objects.create(
            name="Zones agricoles plan", color="#112233"
        )
        self.zone_a = GeoCustomZone.objects.create(
            name="ZA plan",
            color="#aa0000",
            geo_custom_zone_category=zone_category,
            geometry=self.create_bbox_polygon(2.5, 42.5, 5.0, 45.0),
        )
        self.zone_b = GeoCustomZone.objects.create(
            name="Zone naturelle plan",
            color="#00aa00",
            geometry=self.create_bbox_polygon(2.5, 42.5, 5.0, 45.0),
        )

        self.group = create_user_group(name="DDTM 34 plan", geo_zones=[self.herault])
        self.group.feature_flags = [FeatureFlag.PLAN_DE_CONTROLE]
        self.group.save()
        self.group.object_type_categories.add(self.category)
        self.group.geo_custom_zones.add(self.zone_a, self.zone_b)

        self.writer = create_regular_user(email="plan-writer@test.com")
        add_user_to_group(self.writer, self.group)
        self.reader = create_regular_user(email="plan-reader@test.com")
        UserUserGroup.objects.create(
            user=self.reader,
            user_group=self.group,
            user_group_rights=[UserGroupRight.READ],
        )

        self._parcels_count = 0

    # ------------------------------------------------------------------ data

    def make_parcel(self, commune=None, section="AB"):
        commune = commune or self.montpellier
        self._parcels_count += 1
        lon, lat = commune.geometry.centroid.coords
        return create_parcel(
            commune=commune,
            id_parcellaire=f"{commune.iso_code}000{section}{self._parcels_count:04d}",
            x=lon + self._parcels_count * 0.003,
            y=lat,
        )

    def make_object(
        self,
        parcel,
        object_type=None,
        zones=("a",),
        detections=None,
        commune=None,
    ):
        """An object and its detections, each described by a dict: tile_set,
        validation, control, score, prescription, source, official_report_date."""
        commune = commune or (parcel.commune if parcel else self.montpellier)
        detection_object = create_detection_object(
            object_type=object_type or self.cabane, parcel=parcel, commune=commune
        )
        for zone in zones:
            detection_object.geo_custom_zones.add(
                self.zone_a if zone == "a" else self.zone_b
            )

        anchor = parcel.geometry.centroid if parcel else commune.geometry.centroid
        created = []
        for spec in detections or [{}]:
            detection_data = create_detection_data(
                detection_validation_status=spec.get(
                    "validation", DetectionValidationStatus.SUSPECT
                ),
                detection_control_status=spec.get(
                    "control", DetectionControlStatus.NOT_CONTROLLED
                ),
                detection_prescription_status=spec.get("prescription"),
                official_report_date=spec.get("official_report_date"),
            )
            created.append(
                create_detection(
                    detection_object=detection_object,
                    tile_set=spec.get("tile_set", self.ts_2024),
                    geometry=Point(anchor.x, anchor.y, srid=SRID),
                    score=spec.get("score", 0.9),
                    detection_source=spec.get("source", DetectionSource.ANALYSIS),
                    detection_data=detection_data,
                )
            )
        return detection_object, created

    # ------------------------------------------------------------------ api

    def criteria(self, **overrides):
        return {
            "objectTypesUuids": [str(self.cabane.uuid), str(self.piscine.uuid)],
            "customZoneGroups": [[str(self.zone_a.uuid)], [str(self.zone_b.uuid)]],
            "rankingCriteria": ["ZONE_PRIORITY", "OBJECTS_COUNT", "NEW_OBJECTS_COUNT"],
            **overrides,
        }

    def create_plan(self, user=None, user_group=None):
        self.authenticate_user(user or self.writer)
        response = self.client.post(
            PLAN_URL,
            {
                "userGroupUuid": str((user_group or self.group).uuid),
                "name": "Plan de contrôle 2026",
                "startDate": "2026-01-01",
                "endDate": "2026-12-31",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def create_wave(self, plan_uuid, parcels_count=10, **criteria):
        return self.client.post(
            WAVE_URL,
            {
                "controlPlanUuid": plan_uuid,
                "parcelsCount": parcels_count,
                "criteria": self.criteria(**criteria),
            },
            format="json",
        )

    def section(self, plan_uuid, section, **params):
        response = self.client.get(
            PARCEL_URL,
            {"controlPlanUuid": plan_uuid, "section": section, "limit": 100, **params},
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["results"]

    def proposed_parcel_ids(self, plan_uuid, section="PROPOSED"):
        return [row["idParcellaire"] for row in self.section(plan_uuid, section)]

    def plan_and_validate(self, parcels_count=10, **criteria):
        plan = self.create_plan()
        wave = self.create_wave(plan["uuid"], parcels_count=parcels_count, **criteria)
        self.assertEqual(wave.status_code, 201, wave.content)
        response = self.client.post(f"{WAVE_URL}{wave.json()['uuid']}/validate/")
        self.assertEqual(response.status_code, 200, response.content)
        return plan, response.json()
