from django.urls import path
from . import get_tile_view
from . import get_import_infos
from . import get_custom_geometry
from . import get_annotation_grid

URL_PREFIX = "utils/"

urls = [
    path(f"{URL_PREFIX}{view.URL}", view.endpoint, name=view.URL)
    for view in [
        get_tile_view,
        get_import_infos,
        get_custom_geometry,
        get_annotation_grid,
    ]
]
