from core.models.geo_custom_zone import GeoCustomZone
from core.models.object_type_category import ObjectTypeCategory
from core.models.user_group import UserGroup, UserUserGroup
from core.serializers import UuidTimestampedModelSerializerMixin
from core.serializers.geo_custom_zone import GeoCustomZoneSerializer
from core.serializers.object_type_category import ObjectTypeCategorySerializer

from rest_framework import serializers

from core.serializers.utils.query import get_objects
from core.serializers.utils.with_collectivities import (
    WithCollectivitiesInputSerializerMixin,
    WithCollectivitiesSerializerMixin,
    extract_collectivities,
)


class UserGroupSerializer(UuidTimestampedModelSerializerMixin):
    class Meta(UuidTimestampedModelSerializerMixin.Meta):
        model = UserGroup
        fields = UuidTimestampedModelSerializerMixin.Meta.fields + [
            "name",
            "user_group_type",
        ]


class UserGroupDetailSerializer(UserGroupSerializer, WithCollectivitiesSerializerMixin):
    class Meta(UserGroupSerializer.Meta):
        fields = (
            UserGroupSerializer.Meta.fields
            + WithCollectivitiesSerializerMixin.Meta.fields
            + [
                "object_type_categories",
                "geo_custom_zones",
            ]
        )

    object_type_categories = ObjectTypeCategorySerializer(many=True, read_only=True)
    geo_custom_zones = GeoCustomZoneSerializer(many=True, read_only=True)


class UserGroupInputSerializer(
    UserGroupDetailSerializer, WithCollectivitiesInputSerializerMixin
):
    class Meta(UserGroupDetailSerializer.Meta):
        fields = WithCollectivitiesInputSerializerMixin.Meta.fields + [
            "name",
            "geo_custom_zones_uuids",
            "object_type_categories_uuids",
            "user_group_type",
        ]

    geo_custom_zones_uuids = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=True, write_only=True
    )
    object_type_categories_uuids = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=True, write_only=True
    )

    def create(self, validated_data):
        collectivities = extract_collectivities(validated_data)

        geo_custom_zones_uuids = validated_data.pop("geo_custom_zones_uuids", None)
        geo_custom_zones = (
            get_objects(uuids=geo_custom_zones_uuids, model=GeoCustomZone) or []
        )

        object_type_categories_uuids = validated_data.pop(
            "object_type_categories_uuids", None
        )
        object_type_categories = get_objects(
            uuids=object_type_categories_uuids, model=ObjectTypeCategory
        )

        instance = UserGroup(
            **validated_data,
        )

        instance.save()

        if collectivities:
            instance.geo_zones.set(collectivities)

        if geo_custom_zones:
            instance.geo_custom_zones.set(geo_custom_zones)

        if object_type_categories:
            instance.object_type_categories.set(object_type_categories)

        instance.save()

        return instance

    def update(self, instance: UserGroup, validated_data):
        geo_custom_zones_uuids = validated_data.pop("geo_custom_zones_uuids", None)
        geo_custom_zones = (
            get_objects(uuids=geo_custom_zones_uuids, model=GeoCustomZone) or []
        )

        collectivities = extract_collectivities(validated_data)

        object_type_categories_uuids = validated_data.pop(
            "object_type_categories_uuids", None
        )
        object_type_categories = get_objects(
            uuids=object_type_categories_uuids, model=ObjectTypeCategory
        )

        instance.geo_zones.set(collectivities)
        instance.geo_custom_zones.set(geo_custom_zones)

        if object_type_categories is not None:
            instance.object_type_categories.set(object_type_categories)

        for key, value in validated_data.items():
            setattr(instance, key, value)

        instance.save()

        return instance


class UserUserGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserUserGroup
        fields = ["user_group_rights", "user_group"]

    user_group = UserGroupSerializer()


class UserUserGroupInputSerializer(UserUserGroupSerializer):
    class Meta(UserUserGroupSerializer.Meta):
        fields = ["user_group_rights", "user_group_uuid"]

    user_group_uuid = serializers.UUIDField(
        write_only=True,
    )
