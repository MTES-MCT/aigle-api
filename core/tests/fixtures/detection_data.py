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
from core.models.object_type_category import (
    ObjectTypeCategoryObjectType,
    ObjectTypeCategoryObjectTypeStatus,
)


def create_tile_set(name="Test TileSet", date=None, **kwargs):
    if date is None:
        date = timezone.now()

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

    return TileSet.objects.create(**tileset_data)


def create_tile(x=100, y=200, z=18, **kwargs):
    tile, _ = Tile.objects.get_or_create(x=x, y=y, z=z, defaults={**kwargs})
    return tile


def create_object_type_category(name="Test Category", **kwargs):
    category, _ = ObjectTypeCategory.objects.get_or_create(
        name=name, defaults={**kwargs}
    )
    return category


def create_object_type(name="Test Object Type", color=None, **kwargs):
    if color is None:
        color = f"#{hash(name) % 0xFFFFFF:06x}"

    defaults = {"color": color, **kwargs}
    object_type, _ = ObjectType.objects.get_or_create(name=name, defaults=defaults)
    return object_type


def create_object_type_with_category(
    object_type_name="Test Object Type",
    category_name="Test Category",
    color=None,
):
    category = create_object_type_category(name=category_name)
    object_type = create_object_type(name=object_type_name, color=color)
    ObjectTypeCategoryObjectType.objects.get_or_create(
        object_type_category=category,
        object_type=object_type,
        defaults={
            "object_type_category_object_type_status": ObjectTypeCategoryObjectTypeStatus.VISIBLE,
        },
    )
    return object_type, category


def create_detection_object(object_type=None, parcel=None, commune=None, **kwargs):
    if object_type is None:
        object_type = create_object_type()

    return DetectionObject.objects.create(
        object_type=object_type,
        parcel=parcel,
        commune=commune,
        **kwargs,
    )


def create_detection_data(user=None, **kwargs):
    return DetectionData.objects.create(user_last_update=user, **kwargs)


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
    if tile_set is None:
        tile_set = create_tile_set()

    if detection_object is None:
        detection_object = create_detection_object()

    if tile is None:
        tile = create_tile()

    if geometry is None:
        geometry = Point(3.88, 43.61, srid=4326)

    return Detection.objects.create(
        detection_object=detection_object,
        tile=tile,
        tile_set=tile_set,
        geometry=geometry,
        score=score,
        detection_source=detection_source,
        detection_data=detection_data,
        **kwargs,
    )


def create_detection_with_object(
    x=3.88,
    y=43.61,
    score=0.95,
    object_type_name="Swimming Pool",
    tile_set=None,
    parcel=None,
):
    if tile_set is None:
        tile_set = create_tile_set()

    object_type = create_object_type(name=object_type_name)
    detection_object = create_detection_object(object_type=object_type, parcel=parcel)

    geometry = Point(x, y, srid=4326)
    detection = create_detection(
        detection_object=detection_object,
        tile_set=tile_set,
        geometry=geometry,
        score=score,
    )

    return detection_object, detection


def create_complete_detection_setup(parcel=None, commune=None):
    tile_set = create_tile_set(name="Montpellier 2024")
    tile = create_tile(x=100, y=200, z=18)

    object_type, category = create_object_type_with_category(
        object_type_name="Swimming Pool",
        category_name="Leisure",
        color="#00FF00",
    )

    detection_object = create_detection_object(
        object_type=object_type, parcel=parcel, commune=commune
    )

    detection_data = create_detection_data()

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
