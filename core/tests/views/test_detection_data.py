import datetime
import uuid

from django.urls import reverse
from rest_framework import status

from core.models import Detection, TileSetType
from core.models.detection_data import (
    DetectionControlStatus,
    DetectionPrescriptionStatus,
    DetectionValidationStatus,
)
from core.tests.base import BaseAPITestCase
from core.tests.fixtures.users import create_super_admin, create_regular_user
from core.tests.fixtures.detection_data import (
    create_complete_detection_setup,
    create_detection,
    create_detection_data,
    create_detection_object,
    create_object_type,
    create_tile_set,
)
from core.tests.fixtures.geo_data import (
    create_complete_geo_hierarchy,
    create_montpellier_commune,
)


class DetectionDataViewSetTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="ddadmin@test.com")
        self.regular = create_regular_user(email="dduser@test.com")
        self.geo_data = create_complete_geo_hierarchy()
        self.detection_setup = create_complete_detection_setup(
            commune=self.geo_data["communes"]["montpellier"],
        )
        self.detection_data = self.detection_setup["detection_data"]

    def test_list_authenticated(self):
        self.authenticate_user(self.regular)
        url = reverse("DetectionDataViewSet-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_unauthenticated(self):
        url = reverse("DetectionDataViewSet-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_retrieve(self):
        self.authenticate_user(self.regular)
        url = reverse(
            "DetectionDataViewSet-detail",
            kwargs={"uuid": str(self.detection_data.uuid)},
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_retrieve_nonexistent_returns_404(self):
        self.authenticate_user(self.regular)
        url = reverse("DetectionDataViewSet-detail", kwargs={"uuid": str(uuid.uuid4())})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_set_to_control_upgrades_not_verified_to_suspect(self):
        self.detection_data.detection_control_status = (
            DetectionControlStatus.NOT_CONTROLLED
        )
        self.detection_data.detection_validation_status = (
            DetectionValidationStatus.DETECTED_NOT_VERIFIED
        )
        self.detection_data.save()

        self.authenticate_user(self.super_admin)
        url = reverse(
            "DetectionDataViewSet-detail",
            kwargs={"uuid": str(self.detection_data.uuid)},
        )
        response = self.client.patch(
            url,
            {"detectionControlStatus": DetectionControlStatus.TO_CONTROL.value},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.detection_data.refresh_from_db()
        self.assertEqual(
            self.detection_data.detection_control_status,
            DetectionControlStatus.TO_CONTROL,
        )
        self.assertEqual(
            self.detection_data.detection_validation_status,
            DetectionValidationStatus.SUSPECT,
        )


class DetectionBulkUpdateTests(BaseAPITestCase):
    """Bulk edit via DetectionBulkUpdateService.update_multiple_detections."""

    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="bulkadmin@test.com")
        self.tile_set = create_tile_set(name="Bulk 2024")

    def _create_not_verified_detection(self, bbox):
        detection_data = create_detection_data(
            detection_control_status=DetectionControlStatus.NOT_CONTROLLED,
            detection_validation_status=DetectionValidationStatus.DETECTED_NOT_VERIFIED,
        )
        return create_detection(
            detection_object=create_detection_object(),
            tile_set=self.tile_set,
            geometry=self.create_bbox_polygon(*bbox),
            detection_data=detection_data,
        )

    def test_bulk_control_status_persists_cascaded_validation_upgrade(self):
        """Editing only the control status must still persist the validation
        status that set_detection_control_status cascades (NOT_VERIFIED -> SUSPECT)."""
        from core.services.detection_bulk_update import DetectionBulkUpdateService

        detections = [
            self._create_not_verified_detection((3.86, 43.60, 3.87, 43.61)),
            self._create_not_verified_detection((3.88, 43.62, 3.89, 43.63)),
        ]

        DetectionBulkUpdateService(user=self.super_admin).update_multiple_detections(
            detections=detections,
            update_data={"detection_control_status": DetectionControlStatus.TO_CONTROL},
        )

        for detection in detections:
            detection.detection_data.refresh_from_db()
            self.assertEqual(
                detection.detection_data.detection_control_status,
                DetectionControlStatus.TO_CONTROL,
            )
            self.assertEqual(
                detection.detection_data.detection_validation_status,
                DetectionValidationStatus.SUSPECT,
            )


class DetectionDataPrescriptionTests(BaseAPITestCase):
    """Prescription transitions via PATCH detection-data/<uuid>/.

    The detection object's type has a 10-year prescription duration, the edited
    detection sits on a 2024 tile set, so the prescription window covers tile sets
    dated in [2014-01-01, 2024-01-01).
    """

    def setUp(self):
        super().setUp()
        self.super_admin = create_super_admin(email="prescadmin@test.com")
        self.object_type = create_object_type(
            name="Prescriptible Pool", prescription_duration_years=10
        )
        self.detection_object = create_detection_object(object_type=self.object_type)
        # The default detection geometry (3.88, 43.61) sits in Montpellier; prescription
        # only copies onto tile sets whose geo_zones cover the detection.
        self.commune = create_montpellier_commune()
        self.tile_set_2024 = create_tile_set(
            name="Background 2024", date=datetime.date(2024, 1, 1)
        )
        self.tile_set_2024.geo_zones.add(self.commune)
        self.tile_set_2020 = create_tile_set(
            name="Background 2020", date=datetime.date(2020, 1, 1)
        )
        self.tile_set_2020.geo_zones.add(self.commune)

        self.current_data = create_detection_data(
            detection_control_status=DetectionControlStatus.NOT_CONTROLLED,
            detection_validation_status=DetectionValidationStatus.SUSPECT,
        )
        self.current_detection = create_detection(
            detection_object=self.detection_object,
            tile_set=self.tile_set_2024,
            detection_data=self.current_data,
        )

    def _patch_prescription(self, detection_data, prescription_status):
        self.authenticate_user(self.super_admin)
        url = reverse(
            "DetectionDataViewSet-detail", kwargs={"uuid": str(detection_data.uuid)}
        )
        return self.client.patch(
            url,
            {"detectionPrescriptionStatus": prescription_status},
            format="json",
        )

    def test_unprescribe_invalidates_past_detections_instead_of_deleting(self):
        past_data = create_detection_data(
            detection_control_status=DetectionControlStatus.NOT_CONTROLLED,
            detection_validation_status=DetectionValidationStatus.DETECTED_NOT_VERIFIED,
            detection_prescription_status=DetectionPrescriptionStatus.PRESCRIBED,
        )
        past_detection = create_detection(
            detection_object=self.detection_object,
            tile_set=self.tile_set_2020,
            detection_data=past_data,
        )
        self.current_data.detection_prescription_status = (
            DetectionPrescriptionStatus.PRESCRIBED
        )
        self.current_data.save()

        response = self._patch_prescription(
            self.current_data, DetectionPrescriptionStatus.NOT_PRESCRIBED
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(self.detection_object.detections.count(), 2)
        self.assertTrue(Detection.objects.filter(id=past_detection.id).exists())

        past_data.refresh_from_db()
        self.assertEqual(
            past_data.detection_validation_status,
            DetectionValidationStatus.INVALIDATED,
        )
        self.assertEqual(
            past_data.detection_prescription_status,
            DetectionPrescriptionStatus.NOT_PRESCRIBED,
        )
        self.assertEqual(past_data.user_last_update, self.super_admin)

        self.current_data.refresh_from_db()
        self.assertEqual(
            self.current_data.detection_validation_status,
            DetectionValidationStatus.SUSPECT,
        )
        self.assertEqual(
            self.current_data.detection_prescription_status,
            DetectionPrescriptionStatus.NOT_PRESCRIBED,
        )

    def test_prescribe_creates_missing_year_detections_without_duplicates(self):
        # A year of the window that already holds a detection -> no duplicate.
        tile_set_2022 = create_tile_set(
            name="Background 2022", date=datetime.date(2022, 1, 1)
        )
        tile_set_2022.geo_zones.add(self.commune)
        create_detection(
            detection_object=self.detection_object,
            tile_set=tile_set_2022,
            detection_data=create_detection_data(
                detection_control_status=DetectionControlStatus.NOT_CONTROLLED,
                detection_validation_status=DetectionValidationStatus.DETECTED_NOT_VERIFIED,
            ),
        )
        # An INDICATIVE tile set in the window -> never receives a copy.
        tile_set_indicative = create_tile_set(
            name="Indicative 2018",
            date=datetime.date(2018, 1, 1),
            tile_set_type=TileSetType.INDICATIVE,
        )

        response = self._patch_prescription(
            self.current_data, DetectionPrescriptionStatus.PRESCRIBED
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        detections = self.detection_object.detections
        # 2024 + 2022 existing, plus exactly one copy created for 2020.
        self.assertEqual(detections.count(), 3)
        self.assertEqual(detections.filter(tile_set=tile_set_2022).count(), 1)
        self.assertFalse(detections.filter(tile_set=tile_set_indicative).exists())

        created = detections.get(tile_set=self.tile_set_2020)
        self.assertEqual(
            created.detection_data.detection_prescription_status,
            DetectionPrescriptionStatus.PRESCRIBED,
        )
        self.assertEqual(
            created.detection_data.detection_validation_status,
            DetectionValidationStatus.SUSPECT,
        )
