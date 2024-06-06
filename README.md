# Aigle API

## Deploy

### Set up docker

1. Create local volume to persist db data:
```
docker volume create aigle_data
```
2. Create `.env` and `.env.compose` from templates
3. Build and run docker containers:
```
docker build -f Dockerfile -t aigle_api_app_container .
docker-compose --env-file .env -f docker-compose.yml up --force-recreate -d db app
```


## Django

### Add an app

```
python manage.py startapp my_app
```

### Authentication

Authentication in this project is managed with [djoser](https://djoser.readthedocs.io/en/latest/getting_started.html)
- Create a user: `POST` request on `/auth/users/`
- Create a token: `/auth/jwt/create/` and then add received token in header `Authorization` `JWT {token}`
- Check you are connected: `/auth/users/me/`

### Development

#### Set-up

1. Create a virtual environment and activate it (here an example with `venv`)
```
python3 -m venv venv
source venv/bin/activate
```

2. Install dependencies
```
pip3 install -r requirements.txt
```

3. Run local server
```
source .env && source venv/bin/activate && make start
```

During the development, a graphic interface is provided by Django to test the API: make `GET`, `POST`,... requests easily. It is accessible by default on http://127.0.0.1:8000/

I recommend to use an extension like [Requestly](https://chromewebstore.google.com/detail/requestly-intercept-modif/mdnleldcmiljblolnjhpnblkcekpdkpa) to add the token generated in the header and access to protected routes.