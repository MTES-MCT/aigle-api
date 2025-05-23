from typing import List
from core.models.geo_custom_zone import GeoCustomZone
from core.models.geo_sub_custom_zone import GeoSubCustomZone
from core.serializers.geo_custom_zone import GeoCustomZoneWithSubZonesSerializer
from core.serializers.geo_sub_custom_zone import GeoSubCustomZoneMinimalSerializer


def reconciliate_custom_zones_with_sub(
    custom_zones: List[GeoCustomZone], sub_custom_zones: List[GeoSubCustomZone]
):
    sub_zones_by_custom_zone = {}
    for sub_zone in sub_custom_zones:
        custom_zone_id = sub_zone.custom_zone_id
        if custom_zone_id not in sub_zones_by_custom_zone:
            sub_zones_by_custom_zone[custom_zone_id] = []
        sub_zones_by_custom_zone[custom_zone_id].append(sub_zone)

    result = []
    for custom_zone in custom_zones:
        relevant_sub_zones = sub_zones_by_custom_zone.get(custom_zone.id, [])

        temp_serializer = GeoCustomZoneWithSubZonesSerializer(custom_zone)
        custom_zone_data = temp_serializer.data

        custom_zone_data["sub_custom_zones"] = GeoSubCustomZoneMinimalSerializer(
            relevant_sub_zones, many=True
        ).data

        result.append(custom_zone_data)

    return result
