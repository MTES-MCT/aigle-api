# Aigle API

## Development

### Prerequisites

- Python 3.12.3
- Docker (for PostGIS and Redis)

### Set-up

1. Create a virtual environment and activate it

```bash
python3 -m venv venv
source venv/bin/activate
```

2. Install dependencies

```bash
pip3 install -r requirements.txt
```

3. Create `.env` file and replace values

```bash
cp .env.template .env
```

The `.env` file uses plain `KEY=value` format (no `export` prefix). It is read directly by Docker Compose and loaded into your shell with `set -a && source .env && set +a`.

4. Run local server

```bash
source venv/bin/activate
set -a && source .env && set +a
make start
```

### Local database with seed data

Instead of connecting to preprod, you can run a fully local PostGIS with seed data.

**Quick start** (pre-generated seed from S3):

```bash
# 1. Download the seed file
mkdir -p scripts
# Replace <S3_URL> with the actual seed file URL
curl -o scripts/seed_data.sql <S3_URL>

# 2. Start DB, run migrations, load seed (all-in-one)
make local-setup

# 3. Start the server
make server
```

**Generate your own seed** (requires prod/preprod DB access):

```bash
python scripts/extract_dev_data.py \
    --host <DB_HOST> --port <DB_PORT> --dbname <DB_NAME> --user <DB_USER>
# Follow interactive prompts to select regions, departments, communes
# Output: scripts/seed_data.sql

make load-seed
```

**Reset local DB** (start fresh):

```bash
docker compose down -v
make local-setup
```

**Dev users** (password for all: `aigle-dev`):

| Email | Role | Group | Rights |
|-------|------|-------|--------|
| `super-admin@aigle-dev.local` | SUPER_ADMIN | — | — |
| `admin@aigle-dev.local` | ADMIN | — | — |
| `regular@aigle-dev.local` | REGULAR | — | — |
| `ddtm-rw@aigle-dev.local` | REGULAR | DDTM (department) | read/write/annotate |
| `ddtm-ro@aigle-dev.local` | REGULAR | DDTM (department) | read only |
| `ddtm-admin@aigle-dev.local` | ADMIN | DDTM (department) | read/write/annotate |
| `collectivity-rw@aigle-dev.local` | REGULAR | Collectivity (commune) | read/write/annotate |
| `collectivity-ro@aigle-dev.local` | REGULAR | Collectivity (commune) | read only |
| `collectivity-admin@aigle-dev.local` | ADMIN | Collectivity (commune) | read/write/annotate |

### Authentication

Authentication is managed with [djoser](https://djoser.readthedocs.io/en/latest/getting_started.html).

```bash
python manage.py create_super_admin --email myemail@email.com --password mypassword
```

During development, Django provides a browsable API at http://127.0.0.1:8000/. Use an extension like [Requestly](https://chromewebstore.google.com/detail/requestly-intercept-modif/mdnleldcmiljblolnjhpnblkcekpdkpa) to add the JWT token to the header for protected routes.

### Commands

```bash
# import all collectivites
python manage.py import_georegion
python manage.py import_geodepartment
python manage.py import_geocommune

# import hérault
python manage.py import_georegion --insee-codes 76
python manage.py import_geodepartment --insee-codes 34
python manage.py import_geocommune

# insert tiles: for montpellier and its surroundings
python manage.py create_tile --x-min 265750 --x-max 268364 --y-min 190647 --y-max 192325

# import parcels
python manage.py import_parcels
```

### Testing

Tests run against a separate PostgreSQL database (`aigle-test`) on the same server as the main app.

**Local setup:**

1. Set `SQL_DATABASE_TEST=aigle-test` in your `.env` file (falls back to main `SQL_*` connection vars)
2. Run tests:

```bash
make test            # run all tests
make test-coverage   # with coverage report
```

**CI:** Tests run automatically on PRs and pushes to `develop`/`main` via GitHub Actions using a PostGIS service container.

### Emails

To send emails locally, you'll need to install local certificates, [here is how to do it in MacOS](https://korben.info/ssl-sslcertverificationerror-ssl-certificate_verify_failed-certificate-verify-failed-unable-to-get-local-issuer-certificate-_ssl-c1129.html)

## Deploy (Docker)

For full Docker deployment (not needed for local dev):

1. Create `.env.compose` from template (used by the `app` container):

```bash
cp .env.compose.template .env.compose
```

2. Build and run:

```bash
docker build -f Dockerfile -t aigle_api_app_container .
docker compose up --force-recreate -d db app
```

## Useful SQL queries

<details>
<summary>Custom zones — link detections to custom zones</summary>

```sql
insert
    into
    core_detectionobject_geo_custom_zones(
        detectionobject_id,
        geocustomzone_id
    )
select
    distinct
    dobj.id as detectionobject_id,
    {custom_zone_id} as geocustomzone_id
from
    core_detectionobject dobj
join core_detection detec on
    detec.detection_object_id = dobj.id
where
    ST_Within(
        detec.geometry,
        (
        select
            geozone.geometry
        from
            core_geozone geozone
        where
            id = {custom_zone_id}
        )
    )
on conflict do nothing;
```

</details>

<details>
<summary>Remove detections from specific batch</summary>

```sql
delete from core_detection where batch_id = 'sia_2021';

delete
from
    core_detectiondata
where id in (
    select
        core_detectiondata.id
    from
        core_detectiondata
    left join core_detection on
        core_detectiondata.id = core_detection.detection_data_id
    where
        core_detection.detection_data_id is null
);

delete from core_detectionobject_geo_custom_zones where detectionobject_id in (
    select
        obj.id
    from
        core_detectionobject as obj
    left join core_detection as det on
        obj.id = det.detection_object_id
    where
        det.detection_object_id is null
);

delete
from
    core_detectionobject
where id in (
    select
        obj.id
    from
        core_detectionobject as obj
    left join core_detection as det on
        obj.id = det.detection_object_id
    where
        det.detection_object_id is null
);
```

</details>

<details>
<summary>Extract x and y from geozone (for create_tile command)</summary>

```sql
WITH bbox AS (
    SELECT
        ST_XMin(ST_Envelope(geometry)) AS min_lon,
        ST_YMin(ST_Envelope(geometry)) AS min_lat,
        ST_XMax(ST_Envelope(geometry)) AS max_lon,
        ST_YMax(ST_Envelope(geometry)) AS max_lat
    FROM core_geozone WHERE uuid = {geozone_uuid}
)
SELECT
    FLOOR((min_lon + 180) / 360 * POW(2, 19)) AS min_x_tile,
    FLOOR((1 - LN(TAN(RADIANS(max_lat)) + 1 / COS(RADIANS(max_lat))) / PI()) / 2 * POW(2, 19)) AS min_y_tile,
    FLOOR((max_lon + 180) / 360 * POW(2, 19)) AS max_x_tile,
    FLOOR((1 - LN(TAN(RADIANS(min_lat)) + 1 / COS(RADIANS(min_lat))) / PI()) / 2 * POW(2, 19)) AS max_y_tile
FROM bbox;
```

</details>
