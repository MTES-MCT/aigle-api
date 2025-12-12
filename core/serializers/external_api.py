import re
from rest_framework import serializers

from core.models.detection_data import (
    DetectionControlStatus,
)


class UpdateControlStatusExternalApiInputSerializer(serializers.Serializer):
    insee_code = serializers.CharField()
    parcel_code = serializers.CharField()
    control_status = serializers.ChoiceField(choices=DetectionControlStatus.choices)

    def validate_parcel_code(self, value: str) -> str:
        """
        Validate French cadastral parcel code format.

        Expected format: Section (1-2 uppercase letters) + Parcel number (1-4 digits)
        Examples: "B39", "AB1234", "C1"

        French cadastral convention:
        - Section: 1 or 2 uppercase letters (A-Z)
        - Parcel number: 1 to 4 digits
        """
        if not value or not value.strip():
            raise serializers.ValidationError("Le code parcelle est requis")

        value = value.strip().upper()

        # Regex pattern with capture groups: 1-2 uppercase letters followed by 1-4 digits
        parcel_pattern = re.compile(r"^([A-Z]{1,2})(\d{1,4})$")

        match = parcel_pattern.match(value)
        if not match:
            raise serializers.ValidationError(
                "Code parcelle invalide. Format attendu: 1-2 lettres suivi de 1-4 chiffres (exemples : 'B39', 'AB1234')"
            )

        # Extract and store section and number for later use
        self._parcel_section = match.group(1)  # Letters part (e.g., "B", "AB")
        self._parcel_number = int(match.group(2))  # Number part (e.g., "39", "1234")

        return value

    def get_parcel_parts(self) -> tuple[str, int]:
        return (self._parcel_section, self._parcel_number)
