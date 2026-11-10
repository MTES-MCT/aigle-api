from rest_framework import serializers

from core.models.webinar import Webinar
from core.serializers import UuidTimestampedModelSerializerMixin
from core.utils.html import sanitize_rich_text


class WebinarSerializer(UuidTimestampedModelSerializerMixin):
    class Meta(UuidTimestampedModelSerializerMixin.Meta):
        model = Webinar
        fields = UuidTimestampedModelSerializerMixin.Meta.fields + [
            "title",
            "description",
            "date",
            "start_time",
            "end_time",
            "replay_url",
            "registration_url",
            "visio_url",
        ]

    start_time = serializers.TimeField(format="%H:%M", required=False, allow_null=True)
    end_time = serializers.TimeField(format="%H:%M", required=False, allow_null=True)


class WebinarInputSerializer(WebinarSerializer):
    class Meta(WebinarSerializer.Meta):
        fields = [
            field
            for field in WebinarSerializer.Meta.fields
            if field not in UuidTimestampedModelSerializerMixin.Meta.fields
        ]

    def validate_description(self, value: str) -> str:
        return sanitize_rich_text(value)

    def validate(self, attrs):
        # On a PATCH, a missing bound keeps the stored one.
        start_time = attrs.get(
            "start_time", self.instance.start_time if self.instance else None
        )
        end_time = attrs.get(
            "end_time", self.instance.end_time if self.instance else None
        )

        if (start_time is None) != (end_time is None):
            missing_field = "end_time" if start_time else "start_time"
            raise serializers.ValidationError(
                {
                    missing_field: "Renseignez l'heure de début et l'heure de fin, ou aucune des deux"
                }
            )

        if start_time and end_time <= start_time:
            raise serializers.ValidationError(
                {"end_time": "L'heure de fin doit être postérieure à l'heure de début"}
            )

        return attrs

    def to_representation(self, instance):
        return WebinarSerializer(instance, context=self.context).data
