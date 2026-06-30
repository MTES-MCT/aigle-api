from django.urls import path

from core.views.utils import deploy_infos
from . import get_tile_view
from . import get_custom_geometry
from . import get_annotation_grid
from . import contact_us
from . import generate_prior_letter
from . import data_deployment

URL_PREFIX = "utils/"

urls = [
    path(f"{URL_PREFIX}{view.URL}", view.endpoint, name=view.URL.replace(":", ""))
    for view in [
        deploy_infos,
        get_tile_view,
        get_custom_geometry,
        get_annotation_grid,
        contact_us,
        generate_prior_letter,
        data_deployment,
    ]
]

# data_deployment exposes POST run endpoints (whole geozone, single batch, single
# zae layer) alongside its GET list.
for run_url, view, name in [
    (data_deployment.RUN_URL, data_deployment.run_endpoint, "data-deployment-run"),
    (
        data_deployment.BATCH_RUN_URL,
        data_deployment.run_batch_endpoint,
        "data-deployment-batch-run",
    ),
    (
        data_deployment.ZAE_RUN_URL,
        data_deployment.run_zae_endpoint,
        "data-deployment-zae-run",
    ),
]:
    urls.append(path(f"{URL_PREFIX}{run_url}", view, name=name))
