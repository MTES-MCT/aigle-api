#!/usr/bin/env python3
"""
Extract development seed data from a prod/preprod Aigle database.

Connects to a remote PostGIS database, lets you interactively select
geographic zones, then generates a SQL seed file with all related data
(geo hierarchy, detections, parcels, tilesets, object types, custom zones)
plus dev users and groups.

Usage:
    python scripts/extract_dev_data.py \\
        --host db.example.com --port 5432 --dbname aigle --user aigle

    # With explicit password and custom output
    python scripts/extract_dev_data.py \\
        --host db.example.com --port 5432 --dbname aigle --user aigle \\
        --password secret --output scripts/my_seed.sql
"""

import argparse
import base64
import getpass
import hashlib
import os
import sys
import uuid as uuid_module
from datetime import date, datetime, timezone
from decimal import Decimal

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("psycopg2 is required: pip install psycopg2-binary")
    sys.exit(1)


# ── Constants ────────────────────────────────────────────────────────

BATCH_SIZE = 500
SIMPLIFY_TOLERANCE = 0.0001
DEV_PASSWORD = "aigle-dev"
PBKDF2_ITERATIONS = 720000
USER_ID_START = 900001
GROUP_ID_START = 900001

SKIP_ID_TABLES = {
    "core_tileset_geo_zones",
    "core_geocustomzone_geo_zones",
    "core_detectionobject_geo_custom_zones",
    "core_detectionobject_geo_sub_custom_zones",
    "core_parcel_geo_custom_zones",
    "core_parcel_geo_sub_custom_zones",
    "core_usergroup_geo_zones",
    "core_usergroup_geo_custom_zones",
    "core_usergroup_object_type_categories",
    "core_objecttypecategoryobjecttype",
    "core_userusergroup",
}

SEQUENCE_TABLES = [
    "core_geozone",
    "core_tileset",
    "core_tile",
    "core_parcel",
    "core_detectionobject",
    "core_detectiondata",
    "core_detection",
    "core_objecttype",
    "core_objecttypecategory",
    "core_geocustomzonecategory",
    "core_user",
    "core_usergroup",
]


# ── Utilities ────────────────────────────────────────────────────────


def make_django_password(password):
    salt = base64.b64encode(os.urandom(12)).decode("ascii").rstrip("=")
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS
    )
    hash_b64 = base64.b64encode(dk).decode("ascii")
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${hash_b64}"


def format_sql_value(val):
    if val is None:
        return "NULL"
    if isinstance(val, bool):
        return "TRUE" if val else "FALSE"
    if isinstance(val, int):
        return str(val)
    if isinstance(val, (float, Decimal)):
        return str(val)
    if isinstance(val, str):
        if val.startswith("SRID="):
            escaped = val.replace("'", "''")
            return f"ST_GeomFromEWKT('{escaped}')"
        escaped = val.replace("'", "''")
        return f"'{escaped}'"
    if isinstance(val, datetime):
        return f"'{val.isoformat()}'::timestamptz"
    if isinstance(val, date):
        return f"'{val.isoformat()}'::date"
    if isinstance(val, list):
        if not val:
            return "ARRAY[]::varchar[]"
        items = ", ".join(f"'{str(v)}'" for v in val)
        return f"ARRAY[{items}]"
    if isinstance(val, (memoryview, bytes)):
        return f"'\\x{bytes(val).hex()}'"
    return f"'{val}'"


def parse_selection(input_str, max_val):
    indices = set()
    for part in input_str.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part and not part.startswith("-"):
            start, end = part.split("-", 1)
            for i in range(int(start.strip()), int(end.strip()) + 1):
                indices.add(i - 1)
        else:
            indices.add(int(part) - 1)
    invalid = [i for i in indices if i < 0 or i >= max_val]
    if invalid:
        raise ValueError(f"Out of range: {[i + 1 for i in invalid]}")
    return sorted(indices)


def prompt_multi_select(items, prompt_text):
    print(f"\n{prompt_text}")
    print("-" * 70)
    for i, item in enumerate(items, 1):
        print(f"  {i:3d}. {item}")
    print("-" * 70)
    print("  Enter numbers (e.g. 1,3,5 or 1-3 or all)")

    while True:
        choice = input("> ").strip()
        if not choice:
            continue
        if choice.lower() == "all":
            return list(range(len(items)))
        try:
            return parse_selection(choice, len(items))
        except (ValueError, IndexError):
            print(f"  Invalid. Enter numbers between 1 and {len(items)}, or 'all'.")


# ── Database helpers ─────────────────────────────────────────────────


def get_table_columns(conn, table_name):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name, udt_name
            FROM information_schema.columns
            WHERE table_name = %s AND table_schema = 'public'
            ORDER BY ordinal_position
            """,
            [table_name],
        )
        return cur.fetchall()


def extract_rows(
    conn, table_name, where_clause, params, simplify_geo=False, null_columns=None
):
    columns_info = get_table_columns(conn, table_name)
    exclude = set()
    null_cols = null_columns or set()

    if table_name in SKIP_ID_TABLES:
        exclude.add("id")

    select_parts = []
    col_names = []

    for col_name, col_type in columns_info:
        if col_name in exclude:
            continue
        col_names.append(col_name)
        if col_name in null_cols:
            select_parts.append(f"NULL as {col_name}")
        elif col_type == "geometry":
            if simplify_geo:
                select_parts.append(
                    f"ST_AsEWKT(ST_SimplifyPreserveTopology({col_name}, {SIMPLIFY_TOLERANCE})) as {col_name}"
                )
            else:
                select_parts.append(f"ST_AsEWKT({col_name}) as {col_name}")
        else:
            select_parts.append(col_name)

    query = f"SELECT {', '.join(select_parts)} FROM {table_name}"
    if where_clause:
        query += f" WHERE {where_clause}"

    with conn.cursor() as cur:
        cur.execute(query, params or [])
        rows = cur.fetchall()

    return col_names, rows


def generate_inserts(table_name, columns, rows, batch_size=BATCH_SIZE):
    if not rows:
        return ""

    col_list = ", ".join(columns)
    parts = []

    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        value_rows = []
        for row in batch:
            vals = ", ".join(format_sql_value(v) for v in row)
            value_rows.append(f"({vals})")
        parts.append(
            f"INSERT INTO {table_name} ({col_list}) VALUES\n"
            + ",\n".join(value_rows)
            + ";\n"
        )

    return "\n".join(parts)


def extract_and_write(conn, f, section, table_name, where_clause, params, **kwargs):
    cols, rows = extract_rows(conn, table_name, where_clause, params, **kwargs)
    if rows:
        f.write(f"\n-- {section}\n")
        f.write(generate_inserts(table_name, cols, rows))
        f.write("\n")
        print(f"  {table_name}: {len(rows)} rows")
    return rows


# ── Interactive selection ────────────────────────────────────────────


def select_regions(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT r.geozone_ptr_id, r.name, r.insee_code, r.dept_count, r.detection_count
            FROM (
                SELECT gr.geozone_ptr_id, gz.name, gr.insee_code,
                       (SELECT COUNT(*) FROM core_geodepartment gd
                        WHERE gd.region_id = gr.geozone_ptr_id) as dept_count,
                       (SELECT COUNT(*) FROM core_detectionobject dobj
                        JOIN core_geocommune gc ON gc.geozone_ptr_id = dobj.commune_id
                        JOIN core_geodepartment gd ON gd.geozone_ptr_id = gc.department_id
                        WHERE gd.region_id = gr.geozone_ptr_id AND dobj.deleted = false) as detection_count
                FROM core_georegion gr
                JOIN core_geozone gz ON gz.id = gr.geozone_ptr_id
                WHERE gz.deleted = false
            ) r
            WHERE r.detection_count > 0
            ORDER BY r.detection_count DESC, r.name
            """
        )
        regions = cur.fetchall()

    if not regions:
        print("No regions with detections found!")
        sys.exit(1)

    items = [
        f"{r[1]} (INSEE: {r[2]}, {r[3]} depts, {r[4]} detections)" for r in regions
    ]
    selected = prompt_multi_select(
        items, "Select regions (only those with detections):"
    )
    return [regions[i] for i in selected]


def select_departments(conn, region_ids):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.geozone_ptr_id, d.name, d.insee_code, d.region_name,
                   d.commune_count, d.detection_count
            FROM (
                SELECT gd.geozone_ptr_id, gz.name, gd.insee_code, rgz.name as region_name,
                       (SELECT COUNT(*) FROM core_geocommune gc
                        JOIN core_geozone gcz ON gcz.id = gc.geozone_ptr_id
                        WHERE gc.department_id = gd.geozone_ptr_id AND gcz.deleted = false) as commune_count,
                       (SELECT COUNT(*) FROM core_detectionobject dobj
                        JOIN core_geocommune gc ON gc.geozone_ptr_id = dobj.commune_id
                        WHERE gc.department_id = gd.geozone_ptr_id AND dobj.deleted = false) as detection_count
                FROM core_geodepartment gd
                JOIN core_geozone gz ON gz.id = gd.geozone_ptr_id
                JOIN core_geozone rgz ON rgz.id = gd.region_id
                WHERE gz.deleted = false AND gd.region_id = ANY(%s)
            ) d
            WHERE d.detection_count > 0
            ORDER BY d.region_name, d.detection_count DESC, d.name
            """,
            [region_ids],
        )
        departments = cur.fetchall()

    if not departments:
        print("No departments with detections found for selected regions!")
        sys.exit(1)

    items = [
        f"{d[1]} ({d[3]}, INSEE: {d[2]}, {d[4]} communes, {d[5]} detections)"
        for d in departments
    ]
    selected = prompt_multi_select(
        items, "Select departments (only those with detections):"
    )
    return [departments[i] for i in selected]


def select_communes(conn, department_ids):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.geozone_ptr_id, c.name, c.iso_code, c.dept_name, c.detection_count
            FROM (
                SELECT gc.geozone_ptr_id, gz.name, gc.iso_code, dgz.name as dept_name,
                       (SELECT COUNT(*) FROM core_detectionobject dobj
                        WHERE dobj.commune_id = gc.geozone_ptr_id AND dobj.deleted = false) as detection_count
                FROM core_geocommune gc
                JOIN core_geozone gz ON gz.id = gc.geozone_ptr_id
                JOIN core_geozone dgz ON dgz.id = gc.department_id
                WHERE gz.deleted = false AND gc.department_id = ANY(%s)
            ) c
            WHERE c.detection_count > 0
            ORDER BY c.dept_name, c.detection_count DESC, c.name
            """,
            [department_ids],
        )
        communes = cur.fetchall()

    if not communes:
        print("No communes with detections found for selected departments!")
        sys.exit(1)

    items = [f"{c[1]} ({c[3]}, ISO: {c[2]}, {c[4]} detections)" for c in communes]
    selected = prompt_multi_select(
        items, "Select communes (only those with detections):"
    )
    return [communes[i] for i in selected]


# ── Scanning ─────────────────────────────────────────────────────────


def scan_epcis(conn, commune_ids, department_ids):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT gc.epci_id FROM core_geocommune gc
            JOIN core_geoepci ge ON ge.geozone_ptr_id = gc.epci_id
            WHERE gc.geozone_ptr_id = ANY(%s) AND gc.epci_id IS NOT NULL
              AND ge.department_id = ANY(%s)
            """,
            [commune_ids, department_ids],
        )
        return [r[0] for r in cur.fetchall()]


def scan_custom_zones(conn, all_geozone_ids):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT czgz.geocustomzone_id
            FROM core_geocustomzone_geo_zones czgz
            JOIN core_geozone gz ON gz.id = czgz.geocustomzone_id
            WHERE czgz.geozone_id = ANY(%s) AND gz.deleted = false
            """,
            [all_geozone_ids],
        )
        cz_ids = [r[0] for r in cur.fetchall()]

        if not cz_ids:
            return [], [], []

        cur.execute(
            """
            SELECT gscz.geozone_ptr_id
            FROM core_geosubcustomzone gscz
            JOIN core_geozone gz ON gz.id = gscz.geozone_ptr_id
            WHERE gscz.custom_zone_id = ANY(%s) AND gz.deleted = false
            """,
            [cz_ids],
        )
        scz_ids = [r[0] for r in cur.fetchall()]

        cur.execute(
            """
            SELECT DISTINCT gcz.geo_custom_zone_category_id
            FROM core_geocustomzone gcz
            WHERE gcz.geozone_ptr_id = ANY(%s) AND gcz.geo_custom_zone_category_id IS NOT NULL
            """,
            [cz_ids],
        )
        cat_ids = [r[0] for r in cur.fetchall()]

        return cz_ids, scz_ids, cat_ids


def scan_extra_tileset_ids(conn, commune_ids):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT d.tile_set_id
            FROM core_detection d
            JOIN core_detectionobject dobj ON dobj.id = d.detection_object_id
            WHERE dobj.commune_id = ANY(%s) AND d.deleted = false AND dobj.deleted = false
            """,
            [commune_ids],
        )
        return set(r[0] for r in cur.fetchall())


def scan_tileset_ids(conn, all_geozone_ids, extra_ids):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT tsgz.tileset_id
            FROM core_tileset_geo_zones tsgz
            JOIN core_tileset ts ON ts.id = tsgz.tileset_id
            WHERE tsgz.geozone_id = ANY(%s) AND ts.deleted = false
            """,
            [all_geozone_ids],
        )
        ids = set(r[0] for r in cur.fetchall())
    ids.update(extra_ids)
    return list(ids)


def scan_object_type_category_ids(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM core_objecttypecategory WHERE deleted = false")
        return [r[0] for r in cur.fetchall()]


# ── Write sections ───────────────────────────────────────────────────


def write_header(f, metadata):
    f.write(
        f"""-- ============================================
-- Aigle Development Seed Data
-- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
-- Source: {metadata['source']}
-- Regions: {', '.join(metadata['regions'])}
-- Departments: {', '.join(metadata['departments'])}
-- Communes: {', '.join(metadata['communes'])}
--
-- Dev users password: {DEV_PASSWORD}
-- ============================================

BEGIN;

"""
    )


def write_geo_data(conn, f, ids):
    print("\nExtracting geo hierarchy...")

    gz_ids = ids["region"] + ids["department"] + ids["epci"] + ids["commune"]
    extract_and_write(
        conn,
        f,
        "Geo Zones (hierarchy)",
        "core_geozone",
        "id = ANY(%s) AND deleted = false",
        [gz_ids],
    )

    extract_and_write(
        conn,
        f,
        "Regions",
        "core_georegion",
        "geozone_ptr_id = ANY(%s)",
        [ids["region"]],
    )

    extract_and_write(
        conn,
        f,
        "Departments",
        "core_geodepartment",
        "geozone_ptr_id = ANY(%s)",
        [ids["department"]],
    )

    if ids["epci"]:
        extract_and_write(
            conn, f, "EPCIs", "core_geoepci", "geozone_ptr_id = ANY(%s)", [ids["epci"]]
        )

    # Extract communes, nulling out epci_id for EPCIs not in our set
    epci_set = set(ids["epci"])
    cols, rows = extract_rows(
        conn, "core_geocommune", "geozone_ptr_id = ANY(%s)", [ids["commune"]]
    )
    if rows:
        epci_col_idx = cols.index("epci_id") if "epci_id" in cols else None
        if epci_col_idx is not None:
            cleaned_rows = []
            for row in rows:
                row = list(row)
                if row[epci_col_idx] is not None and row[epci_col_idx] not in epci_set:
                    row[epci_col_idx] = None
                cleaned_rows.append(tuple(row))
            rows = cleaned_rows
        f.write("\n-- Communes\n")
        f.write(generate_inserts("core_geocommune", cols, rows))
        f.write("\n")
        print(f"  core_geocommune: {len(rows)} rows")


def write_custom_zones(conn, f, ids):
    cz_ids = ids["custom_zone"]
    scz_ids = ids["sub_custom_zone"]
    cat_ids = ids["cz_category"]

    if not cz_ids:
        print("\n  No custom zones linked to selected geo zones.")
        return

    print("\nExtracting custom zones...")

    if cat_ids:
        extract_and_write(
            conn,
            f,
            "Custom Zone Categories",
            "core_geocustomzonecategory",
            "id = ANY(%s)",
            [cat_ids],
        )

    extract_and_write(
        conn,
        f,
        "Geo Zones (custom)",
        "core_geozone",
        "id = ANY(%s) AND deleted = false",
        [cz_ids],
        simplify_geo=True,
    )
    extract_and_write(
        conn,
        f,
        "Custom Zones",
        "core_geocustomzone",
        "geozone_ptr_id = ANY(%s)",
        [cz_ids],
    )

    if scz_ids:
        extract_and_write(
            conn,
            f,
            "Geo Zones (sub-custom)",
            "core_geozone",
            "id = ANY(%s) AND deleted = false",
            [scz_ids],
            simplify_geo=True,
        )
        extract_and_write(
            conn,
            f,
            "Sub Custom Zones",
            "core_geosubcustomzone",
            "geozone_ptr_id = ANY(%s)",
            [scz_ids],
        )

    all_gz = ids["region"] + ids["department"] + ids["epci"] + ids["commune"]
    extract_and_write(
        conn,
        f,
        "Custom Zone <> Geo Zone",
        "core_geocustomzone_geo_zones",
        "geocustomzone_id = ANY(%s) AND geozone_id = ANY(%s)",
        [cz_ids, all_gz],
    )


def write_object_types(conn, f):
    print("\nExtracting object types...")
    extract_and_write(
        conn,
        f,
        "Object Type Categories",
        "core_objecttypecategory",
        "deleted = false",
        [],
    )
    extract_and_write(conn, f, "Object Types", "core_objecttype", "deleted = false", [])
    extract_and_write(
        conn,
        f,
        "ObjectType <> Category",
        "core_objecttypecategoryobjecttype",
        "object_type_category_id IN (SELECT id FROM core_objecttypecategory WHERE deleted = false) "
        "AND object_type_id IN (SELECT id FROM core_objecttype WHERE deleted = false)",
        [],
    )


def write_tilesets(conn, f, ids):
    ts_ids = ids["tileset"]
    if not ts_ids:
        print("\n  No tilesets found.")
        return

    print("\nExtracting tilesets...")
    extract_and_write(conn, f, "Tilesets", "core_tileset", "id = ANY(%s)", [ts_ids])

    all_gz = (
        ids["region"]
        + ids["department"]
        + ids["epci"]
        + ids["commune"]
        + ids["custom_zone"]
        + ids["sub_custom_zone"]
    )
    extract_and_write(
        conn,
        f,
        "Tileset <> Geo Zone",
        "core_tileset_geo_zones",
        "tileset_id = ANY(%s) AND geozone_id = ANY(%s)",
        [ts_ids, all_gz],
    )


def write_detections(conn, f, ids):
    commune_ids = ids["commune"]
    cz_ids = ids["custom_zone"]
    scz_ids = ids["sub_custom_zone"]

    print("\nExtracting detections...")

    det_subquery = (
        "detection_object_id IN "
        "(SELECT id FROM core_detectionobject WHERE commune_id = ANY(%s) AND deleted = false) "
        "AND deleted = false"
    )

    # Tiles referenced by detections
    tile_where = (
        "id IN (SELECT DISTINCT d.tile_id FROM core_detection d "
        "JOIN core_detectionobject dobj ON dobj.id = d.detection_object_id "
        "WHERE dobj.commune_id = ANY(%s) AND d.deleted = false AND dobj.deleted = false)"
    )
    extract_and_write(conn, f, "Tiles", "core_tile", tile_where, [commune_ids])

    # Collect parcel IDs that exist in our seed (parcels from selected communes)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM core_parcel WHERE commune_id = ANY(%s) AND deleted = false",
            [commune_ids],
        )
        valid_parcel_ids = set(r[0] for r in cur.fetchall())

    # Detection objects — null out parcel_id for parcels not in our set
    cols, rows = extract_rows(
        conn,
        "core_detectionobject",
        "commune_id = ANY(%s) AND deleted = false",
        [commune_ids],
    )

    if not rows:
        print("  No detections in selected communes.")
        return

    parcel_col_idx = cols.index("parcel_id") if "parcel_id" in cols else None
    if parcel_col_idx is not None:
        cleaned_rows = []
        nulled_count = 0
        for row in rows:
            row = list(row)
            if (
                row[parcel_col_idx] is not None
                and row[parcel_col_idx] not in valid_parcel_ids
            ):
                row[parcel_col_idx] = None
                nulled_count += 1
            cleaned_rows.append(tuple(row))
        rows = cleaned_rows
        if nulled_count:
            print(
                f"  Nulled {nulled_count} parcel_id refs to parcels outside selected communes"
            )

    f.write("\n-- Detection Objects\n")
    f.write(generate_inserts("core_detectionobject", cols, rows))
    f.write("\n")
    print(f"  core_detectionobject: {len(rows)} rows")

    # Detection object M2M
    if cz_ids:
        extract_and_write(
            conn,
            f,
            "DetObj <> Custom Zone",
            "core_detectionobject_geo_custom_zones",
            "detectionobject_id IN (SELECT id FROM core_detectionobject WHERE commune_id = ANY(%s) AND deleted = false) "
            "AND geocustomzone_id = ANY(%s)",
            [commune_ids, cz_ids],
        )
    if scz_ids:
        extract_and_write(
            conn,
            f,
            "DetObj <> Sub Custom Zone",
            "core_detectionobject_geo_sub_custom_zones",
            "detectionobject_id IN (SELECT id FROM core_detectionobject WHERE commune_id = ANY(%s) AND deleted = false) "
            "AND geosubcustomzone_id = ANY(%s)",
            [commune_ids, scz_ids],
        )

    # Detection data (null out user FK since those users won't exist locally)
    det_data_where = (
        "id IN (SELECT DISTINCT d.detection_data_id FROM core_detection d "
        "JOIN core_detectionobject dobj ON dobj.id = d.detection_object_id "
        "WHERE dobj.commune_id = ANY(%s) AND d.deleted = false AND dobj.deleted = false "
        "AND d.detection_data_id IS NOT NULL)"
    )
    extract_and_write(
        conn,
        f,
        "Detection Data",
        "core_detectiondata",
        det_data_where,
        [commune_ids],
        null_columns={"user_last_update_id"},
    )

    # Detections
    extract_and_write(
        conn, f, "Detections", "core_detection", det_subquery, [commune_ids]
    )


def write_parcels(conn, f, ids):
    commune_ids = ids["commune"]
    cz_ids = ids["custom_zone"]
    scz_ids = ids["sub_custom_zone"]

    print("\nExtracting parcels...")

    extract_and_write(
        conn,
        f,
        "Parcels",
        "core_parcel",
        "commune_id = ANY(%s) AND deleted = false",
        [commune_ids],
    )

    parcel_subquery = "parcel_id IN (SELECT id FROM core_parcel WHERE commune_id = ANY(%s) AND deleted = false)"

    if cz_ids:
        extract_and_write(
            conn,
            f,
            "Parcel <> Custom Zone",
            "core_parcel_geo_custom_zones",
            f"{parcel_subquery} AND geocustomzone_id = ANY(%s)",
            [commune_ids, cz_ids],
        )
    if scz_ids:
        extract_and_write(
            conn,
            f,
            "Parcel <> Sub Custom Zone",
            "core_parcel_geo_sub_custom_zones",
            f"{parcel_subquery} AND geosubcustomzone_id = ANY(%s)",
            [commune_ids, scz_ids],
        )


def write_users_and_groups(f, ids, metadata):
    print("\nGenerating dev users and groups...")

    password_hash = make_django_password(DEV_PASSWORD)
    now = datetime.now(timezone.utc)

    first_commune_id = ids["commune"][0]
    first_dept_id = ids["department"][0]
    first_commune_name = metadata["communes"][0]
    first_dept_name = metadata["departments"][0]

    users_spec = [
        (USER_ID_START, "super-admin@aigle-dev.local", "SUPER_ADMIN", True, True),
        (USER_ID_START + 1, "admin@aigle-dev.local", "ADMIN", False, False),
        (USER_ID_START + 2, "regular@aigle-dev.local", "REGULAR", False, False),
        (USER_ID_START + 3, "ddtm-rw@aigle-dev.local", "REGULAR", False, False),
        (USER_ID_START + 4, "ddtm-ro@aigle-dev.local", "REGULAR", False, False),
        (USER_ID_START + 5, "ddtm-admin@aigle-dev.local", "ADMIN", False, False),
        (USER_ID_START + 6, "collectivity-rw@aigle-dev.local", "REGULAR", False, False),
        (USER_ID_START + 7, "collectivity-ro@aigle-dev.local", "REGULAR", False, False),
        (
            USER_ID_START + 8,
            "collectivity-admin@aigle-dev.local",
            "ADMIN",
            False,
            False,
        ),
    ]

    user_cols = [
        "id",
        "uuid",
        "email",
        "password",
        "user_role",
        "is_staff",
        "is_active",
        "is_superuser",
        "date_joined",
        "created_at",
        "updated_at",
        "deleted",
        "deleted_at",
        "last_login",
        "last_position",
    ]
    user_rows = []
    for uid, email, role, is_staff, is_superuser in users_spec:
        user_rows.append(
            (
                uid,
                str(uuid_module.uuid4()),
                email,
                password_hash,
                role,
                is_staff,
                True,
                is_superuser,
                now,
                now,
                now,
                False,
                None,
                None,
                None,
            )
        )

    f.write("\n-- Dev Users\n")
    f.write(generate_inserts("core_user", user_cols, user_rows))
    f.write("\n")
    print(f"  core_user: {len(user_rows)} dev users")

    # User groups
    ddtm_group_id = GROUP_ID_START
    coll_group_id = GROUP_ID_START + 1

    group_cols = [
        "id",
        "uuid",
        "created_at",
        "updated_at",
        "deleted",
        "deleted_at",
        "name",
        "user_group_type",
    ]
    group_rows = [
        (
            ddtm_group_id,
            str(uuid_module.uuid4()),
            now,
            now,
            False,
            None,
            f"DDTM {first_dept_name}",
            "DDTM",
        ),
        (
            coll_group_id,
            str(uuid_module.uuid4()),
            now,
            now,
            False,
            None,
            f"Collectivite {first_commune_name}",
            "COLLECTIVITY",
        ),
    ]

    f.write("\n-- User Groups\n")
    f.write(generate_inserts("core_usergroup", group_cols, group_rows))
    f.write("\n")
    print("  core_usergroup: 2 groups")

    # UserGroup <> GeoZone
    ug_gz_cols = ["usergroup_id", "geozone_id"]
    ug_gz_rows = [
        (ddtm_group_id, first_dept_id),
        (coll_group_id, first_commune_id),
    ]
    f.write("\n-- UserGroup <> GeoZone\n")
    f.write(generate_inserts("core_usergroup_geo_zones", ug_gz_cols, ug_gz_rows))
    f.write("\n")

    # UserGroup <> ObjectTypeCategory
    otc_ids = ids.get("object_type_category", [])
    if otc_ids:
        ug_otc_cols = ["usergroup_id", "objecttypecategory_id"]
        ug_otc_rows = []
        for cat_id in otc_ids:
            ug_otc_rows.append((ddtm_group_id, cat_id))
            ug_otc_rows.append((coll_group_id, cat_id))
        f.write("\n-- UserGroup <> ObjectTypeCategory\n")
        f.write(
            generate_inserts(
                "core_usergroup_object_type_categories", ug_otc_cols, ug_otc_rows
            )
        )
        f.write("\n")

    # UserGroup <> GeoCustomZone
    cz_ids = ids.get("custom_zone", [])
    if cz_ids:
        ug_cz_cols = ["usergroup_id", "geocustomzone_id"]
        ug_cz_rows = []
        for cz_id in cz_ids:
            ug_cz_rows.append((ddtm_group_id, cz_id))
            ug_cz_rows.append((coll_group_id, cz_id))
        f.write("\n-- UserGroup <> GeoCustomZone\n")
        f.write(
            generate_inserts("core_usergroup_geo_custom_zones", ug_cz_cols, ug_cz_rows)
        )
        f.write("\n")

    # UserUserGroup
    uug_cols = [
        "created_at",
        "updated_at",
        "user_group_rights",
        "user_id",
        "user_group_id",
    ]
    uug_rows = [
        (now, now, ["READ", "WRITE", "ANNOTATE"], USER_ID_START + 3, ddtm_group_id),
        (now, now, ["READ"], USER_ID_START + 4, ddtm_group_id),
        (now, now, ["READ", "WRITE", "ANNOTATE"], USER_ID_START + 5, ddtm_group_id),
        (now, now, ["READ", "WRITE", "ANNOTATE"], USER_ID_START + 6, coll_group_id),
        (now, now, ["READ"], USER_ID_START + 7, coll_group_id),
        (now, now, ["READ", "WRITE", "ANNOTATE"], USER_ID_START + 8, coll_group_id),
    ]
    f.write("\n-- User <> UserGroup\n")
    f.write(generate_inserts("core_userusergroup", uug_cols, uug_rows))
    f.write("\n")
    print("  core_userusergroup: 6 memberships")


def write_sequence_resets(f):
    f.write("\n-- ============================================\n")
    f.write("-- SEQUENCE RESETS\n")
    f.write("-- ============================================\n\n")

    for table in SEQUENCE_TABLES:
        f.write(
            f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
            f"COALESCE((SELECT MAX(id) FROM {table}), 1));\n"
        )


# ── Main ─────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Extract development seed data from an Aigle database.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/extract_dev_data.py --host db.example.com --port 5432 --dbname aigle --user aigle
  python scripts/extract_dev_data.py --host db.example.com --port 5432 --dbname aigle --user aigle --output my_seed.sql
        """,
    )
    parser.add_argument("--host", required=True, help="Database host")
    parser.add_argument(
        "--port", type=int, default=5432, help="Database port (default: 5432)"
    )
    parser.add_argument("--dbname", required=True, help="Database name")
    parser.add_argument("--user", required=True, help="Database user")
    parser.add_argument("--password", help="Database password (prompted if omitted)")
    parser.add_argument(
        "--output", default="scripts/seed_data.sql", help="Output SQL file path"
    )

    args = parser.parse_args()
    password = (
        args.password
        or os.environ.get("PGPASSWORD")
        or getpass.getpass(f"Password for {args.user}@{args.host}: ")
    )

    print(f"\nConnecting to {args.host}:{args.port}/{args.dbname}...")
    try:
        conn = psycopg2.connect(
            host=args.host,
            port=args.port,
            dbname=args.dbname,
            user=args.user,
            password=password,
        )
        conn.set_client_encoding("UTF8")
    except psycopg2.Error as e:
        print(f"Connection failed: {e}")
        sys.exit(1)
    print("Connected.\n")

    # ── Interactive selection ──

    regions = select_regions(conn)
    region_ids = [r[0] for r in regions]
    region_names = [r[1] for r in regions]

    departments = select_departments(conn, region_ids)
    dept_ids = [d[0] for d in departments]
    dept_names = [d[1] for d in departments]

    communes = select_communes(conn, dept_ids)
    commune_ids = [c[0] for c in communes]
    commune_names = [c[1] for c in communes]

    if not commune_ids:
        print("No communes selected. Exiting.")
        sys.exit(0)

    # ── Scan phase ──

    print("\nScanning related data...")

    ids = {
        "region": region_ids,
        "department": dept_ids,
        "commune": commune_ids,
    }

    ids["epci"] = scan_epcis(conn, commune_ids, dept_ids)
    all_gz = region_ids + dept_ids + commune_ids + ids["epci"]

    ids["custom_zone"], ids["sub_custom_zone"], ids["cz_category"] = scan_custom_zones(
        conn, all_gz
    )

    extra_ts = scan_extra_tileset_ids(conn, commune_ids)
    ids["tileset"] = scan_tileset_ids(conn, all_gz, extra_ts)
    ids["object_type_category"] = scan_object_type_category_ids(conn)

    print(f"  EPCIs: {len(ids['epci'])}")
    print(f"  Custom zones: {len(ids['custom_zone'])}")
    print(f"  Sub custom zones: {len(ids['sub_custom_zone'])}")
    print(f"  Tilesets: {len(ids['tileset'])}")

    # ── Write phase ──

    output_dir = os.path.dirname(args.output)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    metadata = {
        "source": f"{args.host}:{args.port}/{args.dbname}",
        "regions": region_names,
        "departments": dept_names,
        "communes": commune_names,
    }

    with open(args.output, "w", encoding="utf-8") as f:
        write_header(f, metadata)
        write_geo_data(conn, f, ids)
        write_custom_zones(conn, f, ids)
        write_object_types(conn, f)
        write_tilesets(conn, f, ids)
        write_parcels(conn, f, ids)
        write_detections(conn, f, ids)
        write_users_and_groups(f, ids, metadata)
        write_sequence_resets(f)
        f.write("\nCOMMIT;\n")

    conn.close()

    file_size = os.path.getsize(args.output)
    size_mb = file_size / (1024 * 1024)

    print(f"\n{'=' * 50}")
    print(f"Seed file: {args.output} ({size_mb:.1f} MB)")
    print(f"{'=' * 50}")
    print("\nLoad into local DB:")
    print("  make load-seed")
    print(f"\nDev users (password: {DEV_PASSWORD}):")
    print("  super-admin@aigle-dev.local       SUPER_ADMIN")
    print("  admin@aigle-dev.local              ADMIN")
    print("  regular@aigle-dev.local            REGULAR")
    print(
        "  ddtm-rw@aigle-dev.local            REGULAR  DDTM group  read/write/annotate"
    )
    print("  ddtm-ro@aigle-dev.local            REGULAR  DDTM group  read only")
    print(
        "  ddtm-admin@aigle-dev.local         ADMIN    DDTM group  read/write/annotate"
    )
    print(
        "  collectivity-rw@aigle-dev.local    REGULAR  Collectivity  read/write/annotate"
    )
    print("  collectivity-ro@aigle-dev.local    REGULAR  Collectivity  read only")
    print(
        "  collectivity-admin@aigle-dev.local ADMIN    Collectivity  read/write/annotate"
    )


if __name__ == "__main__":
    main()
