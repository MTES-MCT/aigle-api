from core.models.detection import DetectionSource
from core.models.detection_data import (
    DetectionControlStatus,
    DetectionPrescriptionStatus,
    DetectionValidationStatus,
)


DETECTION_CONTROL_STATUSES_NAMES_MAP = {
    DetectionControlStatus.NOT_CONTROLLED: "Non contrôlé",
    DetectionControlStatus.PRIOR_LETTER_SENT: "Courrier préalable envoyé",
    DetectionControlStatus.CONTROLLED_FIELD: "Contrôlé terrain",
    DetectionControlStatus.OFFICIAL_REPORT_DRAWN_UP: "PV dressé",
    DetectionControlStatus.ADMINISTRATIVE_CONSTRAINT: "Astreinte Administrative",
    DetectionControlStatus.OBSERVARTION_REPORT_REDACTED: "Rapport de constatations rédigé",
    DetectionControlStatus.REHABILITATED: "Remis en état",
}


DETECTION_SOURCE_NAMES_MAP = {
    DetectionSource.INTERFACE_DRAWN: "Dessin interface",
    DetectionSource.ANALYSIS: "Analyse",
}

DETECTION_PRESCRIPTION_STATUSES_NAMES_MAP = {
    DetectionPrescriptionStatus.PRESCRIBED: "Prescrit",
    DetectionPrescriptionStatus.NOT_PRESCRIBED: "Non prescrit",
}

DETECTION_VALIDATION_STATUSES_NAMES_MAP = {
    DetectionValidationStatus.DETECTED_NOT_VERIFIED: "Non vérifié",
    DetectionValidationStatus.SUSPECT: "Suspect",
    DetectionValidationStatus.LEGITIMATE: "Légal",
    DetectionValidationStatus.INVALIDATED: "Invalidé",
}
