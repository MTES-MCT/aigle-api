from django.http import JsonResponse

from rest_framework import serializers


from core.utils.tasks import AsyncCommandService
from rest_framework.decorators import api_view, permission_classes

from core.utils.permissions import AdminRolePermission


class EndpointSerializer(serializers.Serializer):
    command = serializers.CharField(required=True, allow_empty=False)
    args = serializers.ListField(required=False, default=list)
    kwargs = serializers.JSONField(required=False, default=dict)


@api_view(["POST"])
@permission_classes([AdminRolePermission])
def endpoint(request):
    endpoint_serializer = EndpointSerializer(data=request.body)
    endpoint_serializer.is_valid(raise_exception=True)

    task_id = AsyncCommandService.run_command_async(
        endpoint_serializer.validated_data.get("command"),
        *endpoint_serializer.validated_data.get("args"),
        **endpoint_serializer.validated_data.get("kwargs"),
    )
    return JsonResponse({"task_id": task_id})


URL = "run-command/"
