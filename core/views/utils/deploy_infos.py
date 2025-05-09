from django.http import JsonResponse


from aigle.settings import DEPLOYMENT_DATETIME


def endpoint():
    return JsonResponse({"datetime": str(DEPLOYMENT_DATETIME)})


URL = "deployment-infos/"
