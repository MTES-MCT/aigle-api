from rest_framework import status
from rest_framework.exceptions import APIException


class Conflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Cette action n'est pas possible dans l'état actuel"
    default_code = "conflict"
