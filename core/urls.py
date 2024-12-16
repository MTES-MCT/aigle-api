from core.views.detection import DetectionViewSet
from core.views.detection_data import DetectionDataViewSet
from core.views.detection_object import DetectionObjectViewSet
from core.views.geo_commune import GeoCommuneViewSet
from core.views.geo_custom_zone import GeoCustomZoneViewSet
from core.views.geo_department import GeoDepartmentViewSet
from core.views.geo_region import GeoRegionViewSet
from core.views.map_settings import MapSettingsView
from core.views.object_type import ObjectTypeViewSet
from core.views.object_type_category import ObjectTypeCategoryViewSet
from core.views.parcel import ParcelViewSet
from core.views.statistics.validation_status_evolution import (
    StatisticsValidationStatusEvolutionView,
)
from core.views.tile_set import TileSetViewSet
from core.views.user import UserViewSet
from rest_framework.routers import DefaultRouter
from core.views.utils import urls as utils_urls
from django.urls import path

from core.views.user_group import UserGroupViewSet

router = DefaultRouter()
router.register("users", UserViewSet, basename="UserViewSet")
router.register("user-group", UserGroupViewSet, basename="UserGroupViewSet")

router.register("geo/commune", GeoCommuneViewSet, basename="GeoCommuneViewSet")
router.register("geo/department", GeoDepartmentViewSet, basename="GeoDepartmentViewSet")
router.register("geo/region", GeoRegionViewSet, basename="GeoRegionViewSet")
router.register(
    "geo/custom-zone", GeoCustomZoneViewSet, basename="GeoCustomZoneViewSet"
)

router.register("parcel", ParcelViewSet, basename="ParcelViewSet")

router.register("object-type", ObjectTypeViewSet, basename="ObjectTypeViewSet")
router.register(
    "object-type-category",
    ObjectTypeCategoryViewSet,
    basename="ObjectTypeCategoryViewSet",
)

router.register("tile-set", TileSetViewSet, basename="TileSetViewSet")

router.register("detection", DetectionViewSet, basename="DetectionViewSet")
router.register(
    "detection-object", DetectionObjectViewSet, basename="DetectionObjectViewSet"
)
router.register("detection-data", DetectionDataViewSet, basename="DetectionDataViewSet")

urlpatterns = router.urls

urlpatterns += [
    path("map-settings/", MapSettingsView.as_view(), name="MapSettingsView")
]

# statistics
urlpatterns += [
    path(
        "statistics/validation-status-evolution/",
        StatisticsValidationStatusEvolutionView.as_view(),
        name="StatisticsValidationStatusEvolutionView",
    )
]

urlpatterns += utils_urls
