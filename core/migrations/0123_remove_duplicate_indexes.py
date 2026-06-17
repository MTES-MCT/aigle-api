# Drops 21 indexes that exactly duplicate an existing PK / unique / FK-auto index on the
# same column(s). Verified against the prod catalog. CONCURRENTLY (atomic=False).
from django.contrib.postgres.operations import RemoveIndexConcurrently
from django.db import migrations


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("core", "0122_deployed_data_detail_commune_index"),
    ]

    operations = [
        # "<table>_uuid_idx" duplicates of the uuid unique index
        RemoveIndexConcurrently(model_name="detection", name="detection_uuid_idx"),
        RemoveIndexConcurrently(
            model_name="detectiondata", name="detectiondata_uuid_idx"
        ),
        RemoveIndexConcurrently(
            model_name="detectionobject", name="detectionobject_uuid_idx"
        ),
        RemoveIndexConcurrently(model_name="geozone", name="geozone_uuid_idx"),
        RemoveIndexConcurrently(model_name="objecttype", name="objecttype_uuid_idx"),
        RemoveIndexConcurrently(
            model_name="objecttypecategory", name="objecttypecategory_uuid_idx"
        ),
        RemoveIndexConcurrently(model_name="parcel", name="parcel_uuid_idx"),
        RemoveIndexConcurrently(model_name="tileset", name="tileset_uuid_idx"),
        RemoveIndexConcurrently(model_name="usergroup", name="usergroup_uuid_idx"),
        # PK / FK / unique duplicates
        RemoveIndexConcurrently(
            model_name="detection", name="core_detect_id_184630_idx"
        ),
        RemoveIndexConcurrently(
            model_name="detection", name="core_detect_detecti_210b06_idx"
        ),
        RemoveIndexConcurrently(
            model_name="detection", name="core_detect_detecti_6048d4_idx"
        ),
        RemoveIndexConcurrently(
            model_name="detectionobject", name="core_detect_object__7e35ba_idx"
        ),
        RemoveIndexConcurrently(
            model_name="parcel", name="core_parcel_commune_de3824_idx"
        ),
        RemoveIndexConcurrently(
            model_name="analyticlog", name="core_analyt_user_id_915201_idx"
        ),
        RemoveIndexConcurrently(
            model_name="useractionlog", name="core_userac_user_id_fbcbd1_idx"
        ),
        RemoveIndexConcurrently(model_name="geozone", name="idx_geozone_id"),
        RemoveIndexConcurrently(
            model_name="geocustomzone", name="core_geocus_geozone_236823_idx"
        ),
        RemoveIndexConcurrently(
            model_name="geosubcustomzone", name="core_geosub_geozone_7bdbef_idx"
        ),
        RemoveIndexConcurrently(
            model_name="commandrun", name="core_comman_task_id_bb1b6e_idx"
        ),
        RemoveIndexConcurrently(model_name="userusergroup", name="idx_user_group_id"),
    ]
