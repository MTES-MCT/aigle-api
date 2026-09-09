import re
from rest_framework import serializers

from core.models.detection_data import (
    DetectionControlStatus,
)


class UpdateControlStatusExternalApiInputSerializer(serializers.Serializer):
    insee_code = serializers.CharField(max_length=5)
    parcel_code = serializers.CharField(max_length=6)
    control_status = serializers.ChoiceField(choices=DetectionControlStatus.choices)

    def validate_insee_code(self, value: str) -> str:
        """Code INSEE de commune : 5 caractères, chiffres — sauf la Corse (2A/2B).

        Sans contrainte, ce champ était la seule entrée libre non bornée de l'API
        externe, alors que parcel_code est validé au caractère près juste en dessous.
        """
        value = (value or "").strip().upper()

        if not re.match(r"^(?:\d{5}|2[AB]\d{3})$", value):
            raise serializers.ValidationError(
                "Code INSEE invalide. Format attendu : 5 chiffres (exemple : '34172')"
            )

        return value

    def validate_parcel_code(self, value: str) -> str:
        """French cadastral parcel code: section (1-2 uppercase letters) + parcel number (1-4 digits), e.g. "AB1234"."""
        if not value or not value.strip():
            raise serializers.ValidationError("Le code parcelle est requis")

        value = value.strip().upper()

        parcel_pattern = re.compile(r"^([A-Z]{1,2})(\d{1,4})$")

        match = parcel_pattern.match(value)
        if not match:
            raise serializers.ValidationError(
                "Code parcelle invalide. Format attendu: 1-2 lettres suivi de 1-4 chiffres (exemples : 'B39', 'AB1234')"
            )

        self._parcel_section = match.group(1)
        self._parcel_number = int(match.group(2))

        return value

    def get_parcel_parts(self) -> tuple[str, int]:
        return (self._parcel_section, self._parcel_number)
