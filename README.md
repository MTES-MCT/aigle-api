# Aigle API

## Deploy

### Set up docker

1. Create local volume to persist db data:

```bash
docker volume create aigle_data
```

2. Create `.env` and `.env.compose` from templates
3. Build and run docker containers:

```bash
docker build -f Dockerfile -t aigle_api_app_container .
docker compose --env-file .env -f docker compose.yml up --force-recreate -d db app
```

## Django

### Add an app

```bash
python manage.py startapp my_app
```

### Authentication

Authentication in this project is managed with [djoser](https://djoser.readthedocs.io/en/latest/getting_started.html)
You can create a user by running command:

```bash
python manage.py create_super_admin --email myemail@email.com --password mypassword
```

### Development

#### Set-up

This project is meant to be used with Python 3.12.3.

1. Create a virtual environment and activate it (here an example with `venv`)

```bash
python3 -m venv venv
source venv/bin/activate
```

2. Install dependencies

```bash
pip3 install -r requirements.txt
```

3. Create `.env` and `.env.compose` file and replace values

```bash
cp .env.template .env
cp .env.compose.template .env.compose
```

4. Run local server

```bash
source .env && source venv/bin/activate && make start
```

During the development, a graphic interface is provided by Django to test the API: make `GET`, `POST`,... requests easily. It is accessible by default on http://127.0.0.1:8000/

I recommend to use an extension like [Requestly](https://chromewebstore.google.com/detail/requestly-intercept-modif/mdnleldcmiljblolnjhpnblkcekpdkpa) to add the token generated in the header and access to protected routes.

### Commands

Some commands need to be run to seed data necessary for the app to works well.

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

### Useful SQL queries


#### Custom zones

Custom zones are big objects so we need to pre-compute and store in database associated zones for each detections. To do so, there is a command BUT this command is not really performant when updating a lot of objects. So here is a SQL request to create links between detections and custom zones:

<details>
  <summary>Query</summary>

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

#### Data from previous AIGLE version (SIA database)

This is the query to get data from previous AIGLE version (SIA database):

<details>
  <summary>Query</summary>

```sql
select
    rel.id,
    rel.polygon as "geometry",
    case
        when (rel.dessine_interface) then 1
        when score is null then 1
        else rel.score
    end as score,
    null as "address",
    ann_t.name_n as "object_type",
    case
        when (rel.dessine_interface) then 'INTERFACE_DRAWN'
        else 'ANALYSIS'
    end
    as "detection_source",
    case
        when rel.signale_terrain then 'CONTROLLED_FIELD'
        when rel.control_status_id = 1 then 'NOT_CONTROLLED'
        when rel.control_status_id = 2 then 'SIGNALED_COMMUNE'
        when rel.control_status_id = 3 then 'SIGNALED_COLLECTIVITY'
        when rel.control_status_id = 4 then 'CONTROLLED_FIELD'
        when rel.control_status_id = 5 then 'REHABILITATED'
        when rel.control_status_id = 6 then 'VERBALIZED'
    end
    as "detection_control_status",
    case
        when rel.validation = 0 then 'INVALIDATED'
        when rel.vrai_legitime
        and rel.vrai_positif
        and not rel.faux_positif then 'LEGITIMATE'
        when not rel.vrai_legitime
        and rel.vrai_positif
        and not rel.faux_positif then 'SUSPECT'
        when not rel.vrai_legitime
        and not rel.vrai_positif
        and rel.faux_positif then 'INVALIDATED'
        when not rel.vrai_legitime
        and not rel.vrai_positif
        and not rel.faux_positif then 'DETECTED_NOT_VERIFIED'
        else 'DETECTED_NOT_VERIFIED'
    end
    as "detection_validation_status",
    case
        when rel.prescrit_manuel then 'PRESCRIBED'
        else 'NOT_PRESCRIBED'
    end
    as "detection_prescription_status",
    rel.validation is not null as "user_reviewed",
    null as tile_x,
    null as tile_y,
    case 
        when tiles.dataset_id = 7 then 'sia_2012'
        when tiles.dataset_id = 4 then 'sia_2015'
        when tiles.dataset_id = 5 then 'sia_2018'
        when tiles.dataset_id = 8 then 'sia_2021'
    end as "batch_id"
from
    relevant_detections rel
join
    annotation_types ann_t on
    (
        case
        when rel.validation is null
            or rel.validation = 0 then rel.type_id
            else rel.validation
        end
    ) = ann_t.id
join
    tiles on
    tiles.id = rel.tile_id
where 
    tiles.dataset_id in (4, 5, 7, 8)
order by
    score desc
```

</details>

#### Remove whole detetctions from specific batch

<details>
	<summary>Query</summary>

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

#### Extract x and y from geozone

To extract the x and y for z=19 from geozone uuid, for example, to run `create_tile` command:

<details>
  <summary>Query</summary>

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

### Emails

To send emails locally, you'll need to install local certificates, [here is how to do it in MacOS](https://korben.info/ssl-sslcertverificationerror-ssl-certificate_verify_failed-certificate-verify-failed-unable-to-get-local-issuer-certificate-_ssl-c1129.html)
