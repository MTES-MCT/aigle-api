from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response

from core.constants.control_plan import (
    ControlPlanFollowUpStatus,
    ControlPlanParcelSection,
)
from core.models.control_plan import (
    ControlPlan,
    ControlPlanParcel,
    ControlPlanStatus,
    ControlPlanWave,
)
from core.permissions.control_plan import ControlPlanPermission
from core.serializers.control_plan import (
    ControlPlanCreateSerializer,
    ControlPlanCriteriaSerializer,
    ControlPlanEligibleCountInputSerializer,
    ControlPlanGroupSerializer,
    ControlPlanInputSerializer,
    ControlPlanOutOfPlanParcelSerializer,
    ControlPlanParcelSerializer,
    ControlPlanSerializer,
    ControlPlanValidationResultSerializer,
    ControlPlanWaveInputSerializer,
    ControlPlanWaveSerializer,
    ControlPlanWaveUpdateSerializer,
)
from core.services.control_plan import (
    ControlPlanParcelService,
    ControlPlanService,
    ControlPlanWaveService,
)
from core.utils.permissions import ControlPlanFeaturePermission
from core.utils.user_action_log import UserActionLogMixin


class ControlPlanPagination(LimitOffsetPagination):
    default_limit = 20
    max_limit = 200


class ControlPlanViewSetMixin(UserActionLogMixin, viewsets.GenericViewSet):
    """Plain GenericViewSet: the BaseViewSetMixin `/count/` route would skip the
    scoping of filter_queryset, and its default writes are not ours."""

    lookup_field = "uuid"
    permission_classes = [ControlPlanFeaturePermission]

    @property
    def control_plan_permission(self) -> ControlPlanPermission:
        if not hasattr(self, "_control_plan_permission"):
            self._control_plan_permission = ControlPlanPermission.from_request(
                self.request
            )
        return self._control_plan_permission

    @property
    def scoped_user_group(self):
        return self.control_plan_permission.scoped_user_group

    def get_serializer_context(self):
        return {
            "request": self.request,
            "control_plan_permission": self.control_plan_permission,
        }

    def _get_plan(self, plan_uuid) -> ControlPlan:
        try:
            control_plan = (
                self.control_plan_permission.plans()
                .select_related("user_group")
                .filter(uuid=plan_uuid)
                .first()
            )
        except DjangoValidationError:
            # a malformed uuid
            control_plan = None
        if control_plan is None:
            raise Http404("Plan de contrôle introuvable")
        return control_plan


class ControlPlanViewSet(ControlPlanViewSetMixin):
    serializer_class = ControlPlanSerializer
    pagination_class = None

    def get_queryset(self):
        return (
            self.control_plan_permission.plans()
            .select_related("user_group")
            .order_by("-start_date", "-created_at")
        )

    def _should_log_user_action(self, request, response) -> bool:
        # a read, sent as a POST for its criteria body
        return self.action != "eligible_count" and super()._should_log_user_action(
            request, response
        )

    def list(self, request):
        queryset = self.get_queryset()

        user_group_uuid = request.query_params.get("userGroupUuid")
        if user_group_uuid:
            queryset = queryset.filter(
                user_group=self.control_plan_permission.get_group(user_group_uuid)
            )

        plan_status = request.query_params.get("controlPlanStatus")
        if plan_status:
            if plan_status not in ControlPlanStatus.values:
                raise ValidationError({"controlPlanStatus": "Statut inconnu"})
            queryset = queryset.filter(control_plan_status=plan_status)

        return Response(self.get_serializer(queryset, many=True).data)

    def retrieve(self, request, uuid=None):
        return Response(self.get_serializer(self.get_object()).data)

    def create(self, request):
        serializer = ControlPlanCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user_group = self.control_plan_permission.get_group(data["user_group_uuid"])
        self.control_plan_permission.validate_edit(user_group)
        control_plan = ControlPlanService.create(
            user_group=user_group,
            name=data["name"],
            start_date=data["start_date"],
            end_date=data["end_date"],
            user=request.user,
        )

        return Response(
            self.get_serializer(control_plan).data, status=status.HTTP_201_CREATED
        )

    def partial_update(self, request, uuid=None):
        control_plan = self.get_object()
        self.control_plan_permission.validate_edit(control_plan.user_group)

        serializer = ControlPlanInputSerializer(
            control_plan, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        control_plan = ControlPlanService.update(
            control_plan, **serializer.validated_data
        )

        return Response(self.get_serializer(control_plan).data)

    def destroy(self, request, uuid=None):
        control_plan = self.get_object()
        self.control_plan_permission.validate_edit(control_plan.user_group)
        ControlPlanService.delete(control_plan)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(methods=["post"], detail=True)
    def close(self, request, uuid=None):
        control_plan = self.get_object()
        self.control_plan_permission.validate_edit(control_plan.user_group)
        control_plan = ControlPlanService.close(control_plan, user=request.user)
        return Response(self.get_serializer(control_plan).data)

    @action(methods=["post"], detail=True, url_path="eligible-count")
    def eligible_count(self, request, uuid=None):
        control_plan = self.get_object()
        self.control_plan_permission.validate_edit(control_plan.user_group)

        serializer = ControlPlanEligibleCountInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            ControlPlanWaveService.eligible_count(
                control_plan,
                criteria=ControlPlanCriteriaSerializer.to_storage(
                    serializer.validated_data["criteria"]
                ),
                user=request.user,
                request_scoped_user_group=self.scoped_user_group,
            )
        )

    @action(methods=["get"], detail=False)
    def groups(self, request):
        return Response(
            ControlPlanGroupSerializer(
                ControlPlanService.groups(self.control_plan_permission), many=True
            ).data
        )

    @action(methods=["get"], detail=False)
    def prerequisites(self, request):
        user_group_uuid = request.query_params.get("userGroupUuid")
        if not user_group_uuid:
            raise ValidationError({"userGroupUuid": "Ce paramètre est requis"})

        user_group = self.control_plan_permission.get_group(user_group_uuid)
        return Response(
            ControlPlanService.prerequisites(
                user=request.user,
                request_scoped_user_group=self.scoped_user_group,
                user_group=user_group,
            )
        )

    @action(methods=["get"], detail=True, url_path="criteria-options")
    def criteria_options(self, request, uuid=None):
        control_plan = self.get_object()
        return Response(
            ControlPlanService.criteria_options(
                user=request.user,
                request_scoped_user_group=self.scoped_user_group,
                user_group=control_plan.user_group,
            )
        )

    @action(methods=["get"], detail=True, url_path="out-of-plan")
    def out_of_plan(self, request, uuid=None):
        control_plan = self.get_object()
        queryset = ControlPlanService.out_of_plan_parcels(
            user=request.user, control_plan=control_plan
        )

        paginator = ControlPlanPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(
            ControlPlanOutOfPlanParcelSerializer(
                page, many=True, context=self.get_serializer_context()
            ).data
        )


class ControlPlanWaveViewSet(ControlPlanViewSetMixin):
    serializer_class = ControlPlanWaveSerializer
    pagination_class = None

    def get_queryset(self):
        return ControlPlanWave.objects.filter(
            control_plan__in=self.control_plan_permission.plans()
        ).select_related("control_plan__user_group")

    def retrieve(self, request, uuid=None):
        return Response(self.get_serializer(self.get_object()).data)

    def create(self, request):
        serializer = ControlPlanWaveInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        control_plan = self._get_plan(data["control_plan_uuid"])
        self.control_plan_permission.validate_edit(control_plan.user_group)
        wave = ControlPlanWaveService.create(
            control_plan=control_plan,
            criteria=ControlPlanCriteriaSerializer.to_storage(data["criteria"]),
            parcels_count=data["parcels_count"],
            user=request.user,
            request_scoped_user_group=self.scoped_user_group,
        )

        return Response(self.get_serializer(wave).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, uuid=None):
        wave = self.get_object()
        self.control_plan_permission.validate_edit(wave.control_plan.user_group)

        # criteria are replaced whole: a partial nested serializer would skip their defaults
        serializer = ControlPlanWaveUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        wave = ControlPlanWaveService.update(
            wave,
            user=request.user,
            request_scoped_user_group=self.scoped_user_group,
            criteria=(
                ControlPlanCriteriaSerializer.to_storage(data["criteria"])
                if "criteria" in data
                else None
            ),
            parcels_count=data.get("parcels_count"),
        )

        return Response(self.get_serializer(wave).data)

    def destroy(self, request, uuid=None):
        wave = self.get_object()
        self.control_plan_permission.validate_edit(wave.control_plan.user_group)
        ControlPlanWaveService.delete_draft(wave)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(methods=["post"], detail=True)
    def validate(self, request, uuid=None):
        wave = self.get_object()
        self.control_plan_permission.validate_edit(wave.control_plan.user_group)
        result = ControlPlanWaveService.validate(
            wave, user=request.user, request_scoped_user_group=self.scoped_user_group
        )
        return Response(ControlPlanValidationResultSerializer(result).data)


class ControlPlanParcelViewSet(ControlPlanViewSetMixin):
    serializer_class = ControlPlanParcelSerializer
    pagination_class = ControlPlanPagination

    def get_queryset(self):
        return (
            ControlPlanParcel.objects.filter(
                control_plan__in=self.control_plan_permission.plans()
            )
            .select_related("control_plan__user_group", "wave", "commune", "parcel")
            .defer("commune__geometry", "parcel__geometry")
        )

    def list(self, request):
        plan_uuid = request.query_params.get("controlPlanUuid")
        if not plan_uuid:
            raise ValidationError({"controlPlanUuid": "Ce paramètre est requis"})
        control_plan = self._get_plan(plan_uuid)

        section = request.query_params.get("section", ControlPlanParcelSection.PLANNED)
        if section not in ControlPlanParcelSection.values:
            raise ValidationError({"section": "Section inconnue"})
        follow_up_status = request.query_params.get("followUpStatus")
        if (
            follow_up_status
            and follow_up_status not in ControlPlanFollowUpStatus.values
        ):
            raise ValidationError({"followUpStatus": "État de suivi inconnu"})

        queryset = ControlPlanParcelService.list_section(
            control_plan, section, follow_up_status=follow_up_status
        )
        page = self.paginate_queryset(queryset)
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    def _get_editable_parcel(self) -> ControlPlanParcel:
        plan_parcel = self.get_object()
        self.control_plan_permission.validate_edit(plan_parcel.control_plan.user_group)
        return plan_parcel

    @action(methods=["post"], detail=True)
    def exclude(self, request, uuid=None):
        plan_parcel = ControlPlanParcelService.exclude(
            self._get_editable_parcel(), user=request.user
        )
        return Response(self.get_serializer(plan_parcel).data)

    @action(methods=["post"], detail=True)
    def include(self, request, uuid=None):
        plan_parcel = ControlPlanParcelService.include(self._get_editable_parcel())
        return Response(self.get_serializer(plan_parcel).data)

    @action(methods=["post"], detail=True, url_path="put-back")
    def put_back(self, request, uuid=None):
        plan_parcel = ControlPlanParcelService.put_back(self._get_editable_parcel())
        return Response(self.get_serializer(plan_parcel).data)

    @action(methods=["post"], detail=True)
    def restore(self, request, uuid=None):
        ControlPlanParcelService.restore(self._get_editable_parcel(), user=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(methods=["post"], detail=True)
    def remove(self, request, uuid=None):
        plan_parcel = ControlPlanParcelService.remove(
            self._get_editable_parcel(),
            user=request.user,
            request_scoped_user_group=self.scoped_user_group,
        )
        return Response(self.get_serializer(plan_parcel).data)

    @action(methods=["get"], detail=True)
    def preview(self, request, uuid=None):
        return Response(
            ControlPlanParcelService.preview(self.get_object(), user=request.user)
        )
