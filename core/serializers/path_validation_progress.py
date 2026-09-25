from rest_framework import serializers

from core.constants.help_center import PATH_VALIDATION_MAX_ITEM_COUNT
from core.models.path_validation_progress import PathValidationProgress
from core.utils.bitmask import mask_to_indices


class PathValidationProgressSerializer(serializers.ModelSerializer):
    class Meta:
        model = PathValidationProgress
        fields = [
            "checked_items",
            "checked_count",
            "item_count",
            "completed_at",
            "updated_at",
        ]

    checked_items = serializers.SerializerMethodField()
    checked_count = serializers.SerializerMethodField()

    def get_checked_items(self, obj):
        return mask_to_indices(obj.checked_items)

    def get_checked_count(self, obj):
        return obj.checked_items.bit_count()


class PathValidationProgressInputSerializer(serializers.Serializer):
    item_count = serializers.IntegerField(
        min_value=1, max_value=PATH_VALIDATION_MAX_ITEM_COUNT
    )
    check = serializers.ListField(
        child=serializers.IntegerField(
            min_value=0, max_value=PATH_VALIDATION_MAX_ITEM_COUNT - 1
        ),
        max_length=PATH_VALIDATION_MAX_ITEM_COUNT,
        required=False,
        default=list,
    )
    uncheck = serializers.ListField(
        child=serializers.IntegerField(
            min_value=0, max_value=PATH_VALIDATION_MAX_ITEM_COUNT - 1
        ),
        max_length=PATH_VALIDATION_MAX_ITEM_COUNT,
        required=False,
        default=list,
    )

    def validate(self, attrs):
        check = set(attrs["check"])
        uncheck = set(attrs["uncheck"])

        if not check and not uncheck:
            raise serializers.ValidationError("Aucun élément à modifier")

        if check & uncheck:
            raise serializers.ValidationError(
                "Un élément ne peut pas être à la fois coché et décoché"
            )

        if any(index >= attrs["item_count"] for index in check | uncheck):
            raise serializers.ValidationError("Indice hors de la liste")

        return attrs
