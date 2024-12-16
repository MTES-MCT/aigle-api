from core.models.geo_custom_zone import (
    GeoCustomZone,
    GeoCustomZoneStatus,
    GeoCustomZoneType,
)
from core.models.user import UserRole
from core.models.user_group import UserGroup
from core.serializers import UuidTimestampedModelSerializerMixin
from rest_framework_gis.serializers import GeoFeatureModelSerializer
from django.core.exceptions import PermissionDenied


class GeoCustomZoneGeoFeatureSerializer(GeoFeatureModelSerializer):
    class Meta:
        model = GeoCustomZone
        geo_field = "geometry"
        fields = [
            "uuid",
            "name",
            "color",
            "geo_custom_zone_status",
            "geo_custom_zone_type",
        ]


class GeoCustomZoneSerializer(UuidTimestampedModelSerializerMixin):
    class Meta(UuidTimestampedModelSerializerMixin.Meta):
        model = GeoCustomZone
        fields = UuidTimestampedModelSerializerMixin.Meta.fields + [
            "name",
            "color",
            "geo_custom_zone_status",
            "geo_custom_zone_type",
        ]

    def update(self, instance: GeoCustomZone, *args, **kwargs):
        user = self.context["request"].user

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

        instance = super().update(instance, *args, **kwargs)

        if not instance.geometry:
            instance.geo_custom_zone_status = GeoCustomZoneStatus.INACTIVE
            instance.save()

        return instance

    def save(self, *args, **kwargs):
        instance = super().save(*args, **kwargs)

        if not instance.geometry:
            instance.geo_custom_zone_status = GeoCustomZoneStatus.INACTIVE
            instance.save()

        user = self.context["request"].user

        if user.user_role != UserRole.SUPER_ADMIN:
            user_groups = UserGroup.objects.filter(user_user_groups__user=user)

            for user_group in user_groups:
                user_group.geo_custom_zones.add(instance)
                user_group.save()

        return instance


class GeoCustomZoneDetailSerializer(GeoCustomZoneSerializer):
    class Meta(GeoCustomZoneSerializer.Meta):
        fields = GeoCustomZoneSerializer.Meta.fields + ["geometry"]
