from core.models.geo_custom_zone import (
    GeoCustomZone,
    GeoCustomZoneStatus,
    GeoCustomZoneType,
)
from core.models.geo_custom_zone_category import GeoCustomZoneCategory
from core.models.user import UserRole
from core.models.user_group import UserGroup
from core.serializers import UuidTimestampedModelSerializerMixin
from rest_framework_gis.serializers import GeoFeatureModelSerializer
from django.core.exceptions import PermissionDenied
from rest_framework import serializers

from core.serializers.geo_sub_custom_zone import GeoSubCustomZoneMinimalSerializer
from core.serializers.utils.with_collectivities import (
    WithCollectivitiesInputSerializerMixin,
    WithCollectivitiesSerializerMixin,
    extract_collectivities,
)
from django.core.exceptions import BadRequest


class GeoCustomZoneGeoFeatureSerializer(GeoFeatureModelSerializer):
    class Meta:
        model = GeoCustomZone
        geo_field = "geometry"
        fields = [
            "uuid",
            "name",
            "name_short",
            "color",
            "geo_custom_zone_status",
            "geo_custom_zone_type",
        ]


class GeoCustomZoneMinimalSerializer(UuidTimestampedModelSerializerMixin):
    class Meta(UuidTimestampedModelSerializerMixin.Meta):
        model = GeoCustomZone
        fields = UuidTimestampedModelSerializerMixin.Meta.fields + [
            "name",
            "name_short",
            "color",
            "geo_custom_zone_status",
            "geo_custom_zone_type",
        ]


class GeoCustomZoneSerializer(GeoCustomZoneMinimalSerializer):
    class Meta(GeoCustomZoneMinimalSerializer.Meta):
        fields = GeoCustomZoneMinimalSerializer.Meta.fields + [
            "geo_custom_zone_category",
        ]

    geo_custom_zone_category = serializers.SerializerMethodField()

    def get_geo_custom_zone_category(self, obj):
        from core.serializers.geo_custom_zone_category import (
            GeoCustomZoneCategorySerializer,
        )

        return (
            GeoCustomZoneCategorySerializer(obj.geo_custom_zone_category).data
            if obj.geo_custom_zone_category
            else None
        )


class GeoCustomZoneWithSubZonesSerializer(GeoCustomZoneSerializer):
    class Meta(GeoCustomZoneSerializer.Meta):
        fields = GeoCustomZoneSerializer.Meta.fields + [
            "sub_custom_zones",
        ]

    sub_custom_zones = GeoSubCustomZoneMinimalSerializer(many=True, read_only=True)


class GeoCustomZoneInputSerializer(
    GeoCustomZoneSerializer, WithCollectivitiesInputSerializerMixin
):
    class Meta(GeoCustomZoneSerializer.Meta):
        fields = WithCollectivitiesInputSerializerMixin.Meta.fields + [
            "name",
            "name_short",
            "color",
            "geo_custom_zone_status",
            "geo_custom_zone_type",
            "geo_custom_zone_category_uuid",
        ]

    geo_custom_zone_category_uuid = serializers.UUIDField(
        write_only=True, required=False, allow_null=True
    )

    def validate(self, attrs):
        geo_custom_zone_category_uuid = attrs.get("geo_custom_zone_category_uuid")

        if not geo_custom_zone_category_uuid and not attrs.get("color"):
            raise serializers.ValidationError(
                {
                    "color": "La couleur est requis lorsqu'une catégorie n'est pas assignée"
                }
            )

        return attrs

    def update(self, instance: GeoCustomZone, validated_data):
        user = self.context["request"].user

        if user.user_role == UserRole.SUPER_ADMIN:
            collectivities = extract_collectivities(validated_data)
            instance.geo_zones.set(collectivities)

        if user.user_role != UserRole.SUPER_ADMIN:
            if instance.geo_custom_zone_type == GeoCustomZoneType.COMMON:
                raise PermissionDenied(
                    "Un administrateur ne peut pas modifier les zones communes"
                )

            user_zones = GeoCustomZone.objects.filter(
                user_groups_custom_geo_zones__user_user_groups__user=user
            )

            if instance.uuid not in [zone.uuid for zone in user_zones]:
                raise PermissionDenied(
                    "Vous n'avez pas les droits pour modifier cette zone"
                )

        geo_custom_zone_category_uuid = validated_data.pop(
            "geo_custom_zone_category_uuid", None
        )

        if geo_custom_zone_category_uuid:
            geo_custom_zone_category = GeoCustomZoneCategory.objects.filter(
                uuid=geo_custom_zone_category_uuid
            ).first()

            if not geo_custom_zone_category:
                raise BadRequest(
                    f"Geo custom zone category with uuid not found: {geo_custom_zone_category_uuid}"
                )

            validated_data["color"] = None

            instance.geo_custom_zone_category = geo_custom_zone_category
        else:
            instance.geo_custom_zone_category = None

        for key, value in validated_data.items():
            setattr(instance, key, value)

        instance.save()

        if (
            not instance.geometry
            and instance.geo_custom_zone_status != GeoCustomZoneStatus.INACTIVE
        ):
            instance.geo_custom_zone_status = GeoCustomZoneStatus.INACTIVE

        instance.save()

        return instance

    def create(self, validated_data):
        user = self.context["request"].user

        collectivities = []

        if user.user_role == UserRole.SUPER_ADMIN:
            collectivities = extract_collectivities(validated_data)

        geo_custom_zone_category_uuid = validated_data.pop(
            "geo_custom_zone_category_uuid", None
        )

        if geo_custom_zone_category_uuid:
            validated_data["color"] = None

        instance = GeoCustomZone(
            **validated_data,
        )
        # for now inactive by default because impossible to set geometry
        instance.geo_custom_zone_status = GeoCustomZoneStatus.INACTIVE

        if collectivities:
            instance.save()
            instance.geo_zones.set(collectivities)

        user = self.context["request"].user

        if user.user_role != UserRole.SUPER_ADMIN:
            user_groups = UserGroup.objects.filter(user_user_groups__user=user)

            for user_group in user_groups:
                user_group.geo_custom_zones.add(instance)
                user_group.save()

        if geo_custom_zone_category_uuid:
            geo_custom_zone_category = GeoCustomZoneCategory.objects.filter(
                uuid=geo_custom_zone_category_uuid
            ).first()

            if not geo_custom_zone_category:
                raise BadRequest(
                    f"Geo custom zone category with uuid not found: {geo_custom_zone_category_uuid}"
                )

            validated_data["name"] = None
            validated_data["name_short"] = None
            validated_data["color"] = None

            instance.save()
            instance.geo_custom_zone_category = geo_custom_zone_category

        instance.save()

        return instance


class GeoCustomZoneWithCollectivitiesSerializer(
    GeoCustomZoneSerializer, WithCollectivitiesSerializerMixin
):
    class Meta(GeoCustomZoneSerializer.Meta):
        fields = (
            GeoCustomZoneSerializer.Meta.fields
            + WithCollectivitiesSerializerMixin.Meta.fields
        )


class GeoCustomZoneDetailSerializer(GeoCustomZoneSerializer):
    class Meta(GeoCustomZoneSerializer.Meta):
        fields = GeoCustomZoneSerializer.Meta.fields + ["geometry"]
