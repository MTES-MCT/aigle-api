from core.models.geo_commune import GeoCommune
from core.models.geo_custom_zone import GeoCustomZone
from core.models.geo_department import GeoDepartment
from core.models.geo_region import GeoRegion
from core.models.geo_zone import GeoZoneType
from core.models.object_type_category import ObjectTypeCategory
from core.models.user_group import UserGroup, UserUserGroup
from core.serializers import UuidTimestampedModelSerializerMixin
from core.serializers.geo_custom_zone import GeoCustomZoneSerializer
from core.serializers.geo_zone import GeoZoneSerializer
from core.serializers.object_type_category import ObjectTypeCategorySerializer

from rest_framework import serializers

from core.serializers.utils.query import get_objects


class UserGroupSerializer(UuidTimestampedModelSerializerMixin):
    class Meta(UuidTimestampedModelSerializerMixin.Meta):
        model = UserGroup
        fields = UuidTimestampedModelSerializerMixin.Meta.fields + [
            "name",
            "user_group_type",
        ]


class UserGroupDetailSerializer(UserGroupSerializer):
    class Meta(UserGroupSerializer.Meta):
        fields = UserGroupSerializer.Meta.fields + [
            "communes",
            "departments",
            "regions",
            "object_type_categories",
            "geo_custom_zones",
        ]

    communes = serializers.SerializerMethodField()
    departments = serializers.SerializerMethodField()
    regions = serializers.SerializerMethodField()
    object_type_categories = ObjectTypeCategorySerializer(many=True, read_only=True)
    geo_custom_zones = GeoCustomZoneSerializer(many=True, read_only=True)

    def get_communes(self, obj):
        return GeoZoneSerializer(
            obj.geo_zones.filter(geo_zone_type=GeoZoneType.COMMUNE),
            many=True,
            read_only=True,
        ).data

    def get_departments(self, obj):
        return GeoZoneSerializer(
            obj.geo_zones.filter(geo_zone_type=GeoZoneType.DEPARTMENT),
            many=True,
            read_only=True,
        ).data

    def get_regions(self, obj):
        return GeoZoneSerializer(
            obj.geo_zones.filter(geo_zone_type=GeoZoneType.REGION),
            many=True,
            read_only=True,
        ).data


class UserGroupInputSerializer(UserGroupDetailSerializer):
    class Meta(UserGroupDetailSerializer.Meta):
        fields = [
            "name",
            "geo_custom_zones_uuids",
            "communes_uuids",
            "departments_uuids",
            "regions_uuids",
            "object_type_categories_uuids",
            "user_group_type",
        ]

    geo_custom_zones_uuids = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=True, write_only=True
    )
    communes_uuids = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=True, write_only=True
    )
    departments_uuids = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=True, write_only=True
    )
    regions_uuids = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=True, write_only=True
    )
    object_type_categories_uuids = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=True, write_only=True
    )

    def create(self, validated_data):
        communes_uuids = validated_data.pop("communes_uuids", None)
        communes = get_objects(uuids=communes_uuids, model=GeoCommune) or []

        departments_uuids = validated_data.pop("departments_uuids", None)
        departments = get_objects(uuids=departments_uuids, model=GeoDepartment) or []

        regions_uuids = validated_data.pop("regions_uuids", None)
        regions = get_objects(uuids=regions_uuids, model=GeoRegion) or []

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

        zones = list(communes) + list(departments) + list(regions)

        if zones:
            instance.geo_zones.set(zones)

        if geo_custom_zones:
            instance.geo_custom_zones.set(geo_custom_zones)

        if object_type_categories:
            instance.object_type_categories.set(object_type_categories)

        instance.save()

        return instance

    def update(self, instance: UserGroup, validated_data):
        communes_uuids = validated_data.pop("communes_uuids", None)
        communes = get_objects(uuids=communes_uuids, model=GeoCommune) or []

        departments_uuids = validated_data.pop("departments_uuids", None)
        departments = get_objects(uuids=departments_uuids, model=GeoDepartment) or []

        regions_uuids = validated_data.pop("regions_uuids", None)
        regions = get_objects(uuids=regions_uuids, model=GeoRegion) or []

        geo_custom_zones_uuids = validated_data.pop("geo_custom_zones_uuids", None)
        geo_custom_zones = (
            get_objects(uuids=geo_custom_zones_uuids, model=GeoCustomZone) or []
        )

        zones = list(communes) + list(departments) + list(regions)

        object_type_categories_uuids = validated_data.pop(
            "object_type_categories_uuids", None
        )
        object_type_categories = get_objects(
            uuids=object_type_categories_uuids, model=ObjectTypeCategory
        )

        instance.geo_zones.set(zones)
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
