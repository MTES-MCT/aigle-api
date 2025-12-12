from core.views.detection import DetectionGeoViewSet
from core.views.detection.detection_list import DetectionListViewSet
from core.views.detection_data import DetectionDataViewSet
from core.views.detection_object import DetectionObjectViewSet
from core.views.external_api import (
    ExternalAPITestView,
    ExternalAPIUpdateControlStatusView,
)
from core.views.geo_commune import GeoCommuneViewSet
from core.views.geo_custom_zone import GeoCustomZoneViewSet
from core.views.geo_custom_zone_category import GeoCustomZoneCategoryViewSet
from core.views.geo_department import GeoDepartmentViewSet
from core.views.geo_region import GeoRegionViewSet
from core.views.map_settings import MapSettingsView
from core.views.object_type import ObjectTypeViewSet
from core.views.object_type_category import ObjectTypeCategoryViewSet
from core.views.parcel import ParcelViewSet
from core.views.run_command import CommandAsyncViewSet
from core.views.statistics.validation_status_evolution import (
    StatisticsValidationStatusEvolutionView,
)
from core.views.statistics.validation_status_global import (
    StatisticsValidationStatusGlobalView,
)
from core.views.statistics.validation_status_object_types_global import (
    StatisticsValidationStatusObjectTypesGlobalView,
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
router.register(
    "geo/custom-zone-category",
    GeoCustomZoneCategoryViewSet,
    basename="GeoCustomZoneCategoryViewSet",
)


router.register("parcel", ParcelViewSet, basename="ParcelViewSet")

router.register("object-type", ObjectTypeViewSet, basename="ObjectTypeViewSet")
router.register(
    "object-type-category",
    ObjectTypeCategoryViewSet,
    basename="ObjectTypeCategoryViewSet",
)

router.register("tile-set", TileSetViewSet, basename="TileSetViewSet")

router.register("detection", DetectionGeoViewSet, basename="DetectionGeoViewSet")
router.register("detection-list", DetectionListViewSet, basename="DetectionListViewSet")
router.register(
    "detection-object", DetectionObjectViewSet, basename="DetectionObjectViewSet"
)
router.register("detection-data", DetectionDataViewSet, basename="DetectionDataViewSet")
router.register("run-command", CommandAsyncViewSet, basename="CommandAsyncViewSet")

urlpatterns = router.urls

urlpatterns += [
    path("map-settings/", MapSettingsView.as_view(), name="MapSettingsView"),
    path("external/test/", ExternalAPITestView.as_view(), name="ExternalAPITestView"),
    path(
        "external/update-control-status/",
        ExternalAPIUpdateControlStatusView.as_view(),
        name="ExternalAPIUpdateControlStatusView",
    ),
]

# statistics
urlpatterns += [
    path(
        "statistics/validation-status-evolution/",
        StatisticsValidationStatusEvolutionView.as_view(),
        name="StatisticsValidationStatusEvolutionView",
    ),
    path(
        "statistics/validation-status-global/",
        StatisticsValidationStatusGlobalView.as_view(),
        name="StatisticsValidationStatusGlobalView",
    ),
    path(
        "statistics/validation-status-object-types-global/",
        StatisticsValidationStatusObjectTypesGlobalView.as_view(),
        name="StatisticsValidationStatusObjectTypesGlobalView",
    ),
]


urlpatterns += utils_urls
