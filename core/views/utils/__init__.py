from django.urls import path

from core.views.utils import deploy_infos
from . import get_tile_view
from . import get_import_infos
from . import get_custom_geometry
from . import get_annotation_grid
from . import contact_us
from . import generate_prior_letter

URL_PREFIX = "utils/"

urls = [
    path(f"{URL_PREFIX}{view.URL}", view.endpoint, name=view.URL)
    for view in [
        deploy_infos,
        get_tile_view,
        get_import_infos,
        get_custom_geometry,
        get_annotation_grid,
        contact_us,
        generate_prior_letter,
    ]
]
