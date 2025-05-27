import os
import tempfile
from django.conf import settings
from django.http import HttpResponse, JsonResponse

from rest_framework import serializers


from common.constants.models import DEFAULT_MAX_LENGTH
from rest_framework.status import HTTP_500_INTERNAL_SERVER_ERROR

from core.utils.odt_processor import ODTTemplateProcessor


class EndpointSerializer(serializers.Serializer):
    firstName = serializers.CharField(max_length=DEFAULT_MAX_LENGTH)
    lastName = serializers.CharField(max_length=DEFAULT_MAX_LENGTH)
    collectivity = serializers.CharField(max_length=DEFAULT_MAX_LENGTH)
    job = serializers.CharField(max_length=DEFAULT_MAX_LENGTH)
    phone = serializers.CharField(max_length=DEFAULT_MAX_LENGTH)
    email = serializers.EmailField()


TEMPLATE_PATH = os.path.join(settings.MEDIA_ROOT, "templates", "test.odt")


def endpoint(request):
    try:
        filename = "test.odt"

        with tempfile.NamedTemporaryFile(suffix=".odt", delete=False) as temp_file:
            temp_output_path = temp_file.name

        try:
            processor = ODTTemplateProcessor(TEMPLATE_PATH)
            processor.replace_placeholders(
                {"template_value": "hello la team"}, temp_output_path
            )

            with open(temp_output_path, "rb") as f:
                response = HttpResponse(
                    f.read(), content_type="application/vnd.oasis.opendocument.text"
                )
                response["Content-Disposition"] = f'attachment; filename="{filename}"'
                return response
        finally:
            os.unlink(temp_output_path)

    except Exception as e:
        return JsonResponse(
            {"error": "Failed to generate document", "details": str(e)},
            status=HTTP_500_INTERNAL_SERVER_ERROR,
        )


URL = "generate-prior-letter/"
