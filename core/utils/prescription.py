from core.models.detection import Detection
from core.models.detection_data import DetectionData, DetectionPrescriptionStatus
from core.models.detection_object import DetectionObject
from dateutil.relativedelta import relativedelta
from simple_history.utils import bulk_update_with_history


def compute_prescription(detection_object: DetectionObject) -> DetectionObject:
    object_type = detection_object.object_type

    # if prescription do not apply to this object type, we reset all prescriptions
    if not object_type.prescription_duration_years:
        detections_to_update = []
        detections_data_to_update = []

        for detection in detection_object.detections.all():
            if detection.auto_prescribed:
                detection.auto_prescribed = False
                detections_to_update.append(detection)

            if detection.detection_data.detection_prescription_status is not None:
                detection.detection_data.detection_prescription_status = None
                detections_data_to_update.append(detection.detection_data)

        if detections_to_update:
            bulk_update_with_history(
                detections_to_update, Detection, ["auto_prescribed"]
            )

        if detections_data_to_update:
            bulk_update_with_history(
                detections_data_to_update,
                DetectionData,
                ["detection_prescription_status"],
            )

        return detection_object

    detections = list(detection_object.detections.all())
    detections = sorted(detections, key=lambda detection: detection.tile_set.date)

    if not detections:
        return detection_object

    oldest_detection = detections[0]
    oldest_detection_date = oldest_detection.tile_set.date

    prescription_duration_years = object_type.prescription_duration_years

    detections_to_update = []
    detections_data_to_update = []

    for detection in detections:
        detection_date = detection.tile_set.date

        nbr_years = relativedelta(detection_date, oldest_detection_date).years

        if nbr_years >= prescription_duration_years:
            # if detection already auto-prescribed, we do nothing
            if detection.auto_prescribed:
                continue

            detection.auto_prescribed = True
            detection.detection_data.detection_prescription_status = (
                DetectionPrescriptionStatus.PRESCRIBED
            )
            detections_to_update.append(detection)
            detections_data_to_update.append(detection.detection_data)
        else:
            if not detection.auto_prescribed:
                continue

            detection.auto_prescribed = False
            detection.detection_data.detection_prescription_status = (
                DetectionPrescriptionStatus.NOT_PRESCRIBED
            )
            detections_to_update.append(detection)
            detections_data_to_update.append(detection.detection_data)

    if detections_to_update:
        bulk_update_with_history(detections_to_update, Detection, ["auto_prescribed"])

    if detections_data_to_update:
        bulk_update_with_history(
            detections_data_to_update, DetectionData, ["detection_prescription_status"]
        )

    return detection_object
