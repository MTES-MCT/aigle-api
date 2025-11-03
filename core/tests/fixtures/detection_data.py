"""
Detection-related test fixtures.

This module provides functions to create detection-related entities for testing:
- TileSets and Tiles
- ObjectTypes and Categories
- DetectionObjects and Detections
- DetectionData
"""

from django.contrib.gis.geos import Point
from django.utils import timezone
from core.models import (
    TileSet,
    TileSetStatus,
    TileSetScheme,
    TileSetType,
    Tile,
    ObjectType,
    ObjectTypeCategory,
    DetectionObject,
    Detection,
    DetectionData,
    DetectionSource,
)


def create_tile_set(name="Test TileSet", date=None, **kwargs):
    """
    Create a TileSet for testing.

    Args:
        name: TileSet name
        date: Date of the tileset (defaults to now)
        **kwargs: Additional TileSet fields

    Returns:
        TileSet object
    """
    if date is None:
        date = timezone.now()

    # Check if TileSet already exists
    try:
        return TileSet.objects.get(name=name)
    except TileSet.DoesNotExist:
        pass

    tileset_data = {
        "name": name,
        "url": kwargs.pop(
            "url", f"https://example.com/tiles/{name.lower().replace(' ', '_')}"
        ),
        "tile_set_status": kwargs.pop("tile_set_status", TileSetStatus.VISIBLE),
        "date": date,
        "tile_set_scheme": kwargs.pop("tile_set_scheme", TileSetScheme.xyz),
        "tile_set_type": kwargs.pop("tile_set_type", TileSetType.BACKGROUND),
        **kwargs,
    }

    tileset = TileSet.objects.create(**tileset_data)
    return tileset


def create_tile(tile_set=None, x=100, y=200, z=18, **kwargs):
    """
    Create a Tile for testing.

    Args:
        tile_set: TileSet object (creates one if None)
        x: Tile X coordinate
        y: Tile Y coordinate
        z: Tile Z (zoom) level
        **kwargs: Additional Tile fields

    Returns:
        Tile object
    """
    if tile_set is None:
        tile_set = create_tile_set()

    tile_data = {"tile_set": tile_set, "x": x, "y": y, "z": z, **kwargs}

    tile = Tile.objects.create(**tile_data)
    return tile


def create_object_type_category(name="Test Category", color="#FF0000", **kwargs):
    """
    Create an ObjectTypeCategory for testing.

    Args:
        name: Category name
        color: Hex color code
        **kwargs: Additional category fields

    Returns:
        ObjectTypeCategory object
    """
    defaults = {"color": color, **kwargs}

    category, _ = ObjectTypeCategory.objects.get_or_create(name=name, defaults=defaults)
    return category


def create_object_type(name="Test Object Type", category=None, color=None, **kwargs):
    """
    Create an ObjectType for testing.

    Args:
        name: Object type name
        category: ObjectTypeCategory (creates one if None)
        color: Hex color code
        **kwargs: Additional object type fields

    Returns:
        ObjectType object
    """
    if category is None:
        category = create_object_type_category()

    if color is None:
        color = category.color

    defaults = {"category": category, "color": color, **kwargs}

    object_type, _ = ObjectType.objects.get_or_create(name=name, defaults=defaults)
    return object_type


def create_detection_object(object_type=None, tile_set=None, parcel=None, **kwargs):
    """
    Create a DetectionObject for testing.

    Args:
        object_type: ObjectType (creates one if None)
        tile_set: TileSet (creates one if None)
        parcel: Parcel object (optional)
        **kwargs: Additional detection object fields

    Returns:
        DetectionObject object
    """
    if object_type is None:
        object_type = create_object_type()

    if tile_set is None:
        tile_set = create_tile_set()

    detection_object_data = {
        "object_type": object_type,
        "tile_set": tile_set,
        "parcel": parcel,
        **kwargs,
    }

    detection_object = DetectionObject.objects.create(**detection_object_data)
    return detection_object


def create_detection_data(user=None, **kwargs):
    """
    Create DetectionData for testing.

    Args:
        user: User who last updated (optional)
        **kwargs: Additional detection data fields

    Returns:
        DetectionData object
    """
    detection_data_fields = {"user_last_update": user, **kwargs}

    detection_data = DetectionData.objects.create(**detection_data_fields)
    return detection_data


def create_detection(
    detection_object=None,
    tile=None,
    tile_set=None,
    geometry=None,
    score=0.95,
    detection_source=DetectionSource.ANALYSIS,
    detection_data=None,
    **kwargs,
):
    """
    Create a Detection for testing.

    Args:
        detection_object: DetectionObject (creates one if None)
        tile: Tile (creates one if None)
        tile_set: TileSet (uses detection_object's or creates one)
        geometry: Point geometry (creates default if None)
        score: Detection score (0-1)
        detection_source: Detection source
        detection_data: DetectionData (optional)
        **kwargs: Additional detection fields

    Returns:
        Detection object
    """
    if detection_object is None:
        detection_object = create_detection_object()

    if tile_set is None:
        tile_set = detection_object.tile_set

    if tile is None:
        tile = create_tile(tile_set=tile_set)

    if geometry is None:
        # Default to Montpellier center
        geometry = Point(3.88, 43.61, srid=4326)

    detection_fields = {
        "detection_object": detection_object,
        "tile": tile,
        "tile_set": tile_set,
        "geometry": geometry,
        "score": score,
        "detection_source": detection_source,
        "detection_data": detection_data,
        **kwargs,
    }

    detection = Detection.objects.create(**detection_fields)
    return detection


def create_detection_with_object(
    x=3.88,
    y=43.61,
    score=0.95,
    object_type_name="Swimming Pool",
    tile_set=None,
    parcel=None,
):
    """
    Create a complete detection with object for testing.

    Args:
        x: Longitude
        y: Latitude
        score: Detection score
        object_type_name: Name of object type
        tile_set: TileSet (creates one if None)
        parcel: Parcel (optional)

    Returns:
        tuple: (DetectionObject, Detection)
    """
    if tile_set is None:
        tile_set = create_tile_set()

    object_type = create_object_type(name=object_type_name)
    detection_object = create_detection_object(
        object_type=object_type, tile_set=tile_set, parcel=parcel
    )

    geometry = Point(x, y, srid=4326)
    detection = create_detection(
        detection_object=detection_object,
        tile_set=tile_set,
        geometry=geometry,
        score=score,
    )

    return detection_object, detection


def create_complete_detection_setup(parcel=None, commune=None):
    """
    Create a complete detection setup for testing.

    Returns:
        dict: Dictionary containing all created detection objects:
            - tile_set: TileSet
            - tile: Tile
            - category: ObjectTypeCategory
            - object_type: ObjectType
            - detection_object: DetectionObject
            - detection_data: DetectionData
            - detection: Detection
    """
    tile_set = create_tile_set(name="Montpellier 2024")
    tile = create_tile(tile_set=tile_set, x=100, y=200, z=18)

    category = create_object_type_category(name="Leisure", color="#00FF00")
    object_type = create_object_type(name="Swimming Pool", category=category)

    detection_object = create_detection_object(
        object_type=object_type, tile_set=tile_set, parcel=parcel
    )

    detection_data = create_detection_data()

    # Create detection in Montpellier
    geometry = Point(3.88, 43.61, srid=4326)
    detection = create_detection(
        detection_object=detection_object,
        tile=tile,
        tile_set=tile_set,
        geometry=geometry,
        score=0.95,
        detection_data=detection_data,
    )

    return {
        "tile_set": tile_set,
        "tile": tile,
        "category": category,
        "object_type": object_type,
        "detection_object": detection_object,
        "detection_data": detection_data,
        "detection": detection,
    }
