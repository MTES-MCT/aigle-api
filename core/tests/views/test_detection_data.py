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
from core.tests.fixtures.geo_data import create_complete_geo_hierarchy


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
        self.tile_set_2024 = create_tile_set(
            name="Background 2024", date=datetime.date(2024, 1, 1)
        )
        self.tile_set_2020 = create_tile_set(
            name="Background 2020", date=datetime.date(2020, 1, 1)
        )

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

        # No detection row was deleted.
        self.assertEqual(self.detection_object.detections.count(), 2)
        self.assertTrue(Detection.objects.filter(id=past_detection.id).exists())

        # The past detection was invalidated and unprescribed instead.
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

        # The edited detection keeps its own validation status.
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
