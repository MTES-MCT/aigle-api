from datetime import date

from django.contrib.gis.geos import Point

from core.models.detection_data import (
    DetectionControlStatus,
    DetectionPrescriptionStatus,
    DetectionValidationStatus,
)
from core.tests.base import BaseAPITestCase
from core.tests.fixtures.detection_data import (
    create_detection,
    create_detection_data,
    create_detection_object,
    create_object_type,
    create_tile,
    create_tile_set,
)
from core.tests.fixtures.geo_data import (
    create_beziers_commune,
    create_herault_department,
    create_montpellier_commune,
)
from core.tests.fixtures.users import create_super_admin


class PrescriptionScopingTests(BaseAPITestCase):
    """Prescribing must only create detections on tile sets that cover the object.

    Regression guard: the prescribe branch selected tile sets by DATE ONLY, so it
    cloned the detection onto every tile set in the window across the whole country.
    """

    def setUp(self):
        super().setUp()
        self.user = create_super_admin()  # unrestricted -> passes can_edit
        self.authenticate_user(self.user)

        herault = create_herault_department()
        montpellier = create_montpellier_commune(department=herault)
        beziers = create_beziers_commune(department=herault)  # far from Montpellier

        object_type = create_object_type(name="Cabane", prescription_duration_years=5)

        # window = [2018-01-01, 2023-01-01): near + far both fall inside it
        self.ts_current = create_tile_set(name="MTP 2023", date=date(2023, 1, 1))
        self.ts_current.geo_zones.add(montpellier)
        self.ts_near = create_tile_set(name="MTP 2020", date=date(2020, 1, 1))
        self.ts_near.geo_zones.add(montpellier)
        self.ts_far = create_tile_set(name="Beziers 2021", date=date(2021, 1, 1))
        self.ts_far.geo_zones.add(beziers)

        self.obj = create_detection_object(object_type=object_type, commune=montpellier)
        self.detection_data = create_detection_data(
            detection_control_status=DetectionControlStatus.NOT_CONTROLLED,
            detection_validation_status=DetectionValidationStatus.SUSPECT,
            detection_prescription_status=DetectionPrescriptionStatus.NOT_PRESCRIBED,
        )
        create_detection(
            detection_object=self.obj,
            tile=create_tile(),
            tile_set=self.ts_current,
            geometry=Point(3.88, 43.61, srid=4326),  # inside Montpellier, not Béziers
            detection_data=self.detection_data,
        )

    def test_prescription_only_creates_on_covering_tile_sets(self):
        response = self.client.patch(
            f"/api/detection-data/{self.detection_data.uuid}/",
            {"detectionPrescriptionStatus": "PRESCRIBED"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

        tile_set_ids = set(self.obj.detections.values_list("tile_set_id", flat=True))
        # original + one prescribed copy on the covering tile set only
        self.assertEqual(self.obj.detections.count(), 2)
        self.assertIn(self.ts_near.id, tile_set_ids)  # covering -> created
        self.assertNotIn(self.ts_far.id, tile_set_ids)  # far -> NOT created

    def test_prescribe_object_type_without_duration_does_not_crash(self):
        object_type = create_object_type(
            name="No duration", prescription_duration_years=None
        )
        obj = create_detection_object(object_type=object_type)
        detection_data = create_detection_data(
            detection_control_status=DetectionControlStatus.NOT_CONTROLLED,
            detection_validation_status=DetectionValidationStatus.SUSPECT,
            detection_prescription_status=DetectionPrescriptionStatus.NOT_PRESCRIBED,
        )
        create_detection(
            detection_object=obj,
            tile=create_tile(),
            tile_set=self.ts_current,
            geometry=Point(3.88, 43.61, srid=4326),
            detection_data=detection_data,
        )

        response = self.client.patch(
            f"/api/detection-data/{detection_data.uuid}/",
            {"detectionPrescriptionStatus": "PRESCRIBED"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)  # no 500
        self.assertEqual(obj.detections.count(), 1)  # no fan-out
