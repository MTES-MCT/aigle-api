from collections import defaultdict
import json
from django.http import JsonResponse


from core.models.detection import Detection
from django.contrib.gis.geos import Polygon

from core.models.tile import Tile
from core.views.detection.detection_geo import DetectionGeoFilter

from django.core.exceptions import BadRequest
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from django.contrib.gis.geos import MultiPolygon
from django.db.models import F, Value, IntegerField, Func, ExpressionWrapper
from django.contrib.gis.db.models.aggregates import Union
from django.db.models import Count


GRID_SIZE = 6


def serialize_to_feature_collection(grid_elements):
    features = []
    for element in grid_elements:
        features.append(
            {
                "type": "Feature",
                "geometry": json.loads(element["geometry"].geojson),
                "properties": {
                    "x": element["x"],
                    "y": element["y"],
                    "total": element["total"],
                    "reviewed": element["reviewed"],
                    "text": f'{element["reviewed"]} vérifiés/{element["total"]} détectés',
                    "textShort": f'{element["reviewed"]}/{element["total"]}',
                },
            }
        )

    return {
        "type": "FeatureCollection",
        "features": features,
    }


class Floor(Func):
    function = "FLOOR"
    arity = 1


class Envelope(Func):
    function = "ST_Envelope"
    arity = 1


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def endpoint(request):
    polygon_requested = Polygon.from_bbox(
        (
            request.GET["swLng"],
            request.GET["swLat"],
            request.GET["neLng"],
            request.GET["neLat"],
        )
    )
    # extend polygon to be sure to have all tiles
    polygon_requested = polygon_requested.buffer(0.01)

    # Adjust x and y by GRID_SIZE for grouping
    tiles = (
        Tile.objects.filter(geometry__intersects=polygon_requested)
        .annotate(
            grouped_x=ExpressionWrapper(
                Floor(F("x") / Value(GRID_SIZE)) * GRID_SIZE,
                output_field=IntegerField(),
            ),
            grouped_y=ExpressionWrapper(
                Floor(F("y") / Value(GRID_SIZE)) * GRID_SIZE,
                output_field=IntegerField(),
            ),
            nbr=Count("id"),
        )
        .filter(
            # exclude grouped tiles that are not full to avoid mistakes in counting
            nbr=GRID_SIZE
            * GRID_SIZE
        )
    )

    grouped_tiles = tiles.values("grouped_x", "grouped_y").annotate(
        # enveloppe because union of overlapping geometries cause artifacts
        group_geometry=Envelope(Union("geometry"))
    )

    all_geometries = MultiPolygon([tile["group_geometry"] for tile in grouped_tiles])
    sw_lng, sw_lat, ne_lng, ne_lat = all_geometries.extent

    # we want to get all detections contained in the grid
    data_requested = request.GET.copy()

    data_requested["swLng"] = sw_lng
    data_requested["swLat"] = sw_lat
    data_requested["neLng"] = ne_lng
    data_requested["neLat"] = ne_lat

    filterset = DetectionGeoFilter(
        data_requested, queryset=Detection.objects, request=request
    )

    if not filterset.is_valid():
        raise BadRequest(filterset.errors)

    queryset = filterset.qs.values_list(
        "id", "detection_data__detection_validation_status", "geometry"
    )
    detections_raw = queryset.all()

    # Initialize result container
    grid_items_total = defaultdict(int)
    grid_items_reviewed = defaultdict(int)

    # Iterate over detections and count occurrences in each grid cell
    for detection_raw in detections_raw:
        detection_centroid = detection_raw[2].centroid
        for tile in grouped_tiles:
            if tile["group_geometry"].contains(detection_centroid):
                grid_items_total[(tile["grouped_x"], tile["grouped_y"])] += 1

                if detection_raw[1] != "DETECTED_NOT_VERIFIED":
                    grid_items_reviewed[(tile["grouped_x"], tile["grouped_y"])] += 1

                break

    # Output results
    grid_with_counts = [
        {
            "geometry": tile["group_geometry"],
            "x": tile["grouped_x"],
            "y": tile["grouped_y"],
            "total": grid_items_total.get((tile["grouped_x"], tile["grouped_y"]), 0),
            "reviewed": grid_items_reviewed.get(
                (tile["grouped_x"], tile["grouped_y"]), 0
            ),
        }
        for tile in grouped_tiles
    ]

    return JsonResponse(serialize_to_feature_collection(grid_with_counts), safe=False)


URL = "get-annotation-grid/"
