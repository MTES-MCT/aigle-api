from core.models.object_type_category import (
    ObjectTypeCategory,
    ObjectTypeCategoryObjectType,
)
from core.serializers import UuidTimestampedModelSerializerMixin

from rest_framework import serializers

from core.serializers.object_type import ObjectTypeSerializer


class ObjectTypeCategorySerializer(UuidTimestampedModelSerializerMixin):
    class Meta(UuidTimestampedModelSerializerMixin.Meta):
        model = ObjectTypeCategory
        fields = UuidTimestampedModelSerializerMixin.Meta.fields + ["name"]


class ObjectTypeCategoryObjectTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ObjectTypeCategoryObjectType
        fields = ["object_type_category_object_type_status", "object_type"]

    object_type = ObjectTypeSerializer(read_only=True)


class ObjectTypeCategoryDetailSerializer(ObjectTypeCategorySerializer):
    class Meta(ObjectTypeCategorySerializer.Meta):
        fields = ObjectTypeCategorySerializer.Meta.fields + [
            "object_type_category_object_types"
        ]

    object_type_category_object_types = ObjectTypeCategoryObjectTypeSerializer(
        many=True, read_only=True
    )


class ObjectTypeCategoryObjectTypeInputSerializer(
    ObjectTypeCategoryObjectTypeSerializer
):
    class Meta(ObjectTypeCategoryObjectTypeSerializer.Meta):
        fields = ["object_type_category_object_type_status", "object_type_uuid"]

    object_type_uuid = serializers.UUIDField(write_only=True)


class ObjectTypeCategoryInputSerializer(ObjectTypeCategorySerializer):
    class Meta(ObjectTypeCategorySerializer.Meta):
        fields = ["name", "object_type_category_object_types"]

    object_type_category_object_types = ObjectTypeCategoryObjectTypeInputSerializer(
        many=True, required=False, allow_empty=True, write_only=True
    )

    def create(self, validated_data):
        from core.services.object_type_category import ObjectTypeCategoryService

        object_type_category_object_types = validated_data.pop(
            "object_type_category_object_types", None
        )

        try:
            return ObjectTypeCategoryService.create_object_type_category(
                name=validated_data["name"],
                object_type_category_object_types=object_type_category_object_types,
            )
        except serializers.ValidationError:
            raise

    def update(self, instance: ObjectTypeCategory, validated_data):
        from core.services.object_type_category import ObjectTypeCategoryService

        object_type_category_object_types = validated_data.pop(
            "object_type_category_object_types", None
        )

        try:
            return ObjectTypeCategoryService.update_object_type_category(
                instance=instance,
                name=validated_data.get("name"),
                object_type_category_object_types=object_type_category_object_types,
            )
        except serializers.ValidationError:
            raise
