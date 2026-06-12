from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def endpoint(request, detection_object_uuid):
    from core.permissions.scope import resolve_scoped_user_group
    from core.services.prior_letter import PriorLetterService

    service = PriorLetterService(
        user=request.user,
        scoped_user_group=resolve_scoped_user_group(request),
    )
    return service.generate_document(detection_object_uuid)


URL = "generate-prior-letter/<uuid:detection_object_uuid>/"
