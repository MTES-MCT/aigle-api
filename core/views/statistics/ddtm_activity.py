from rest_framework import serializers
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from core.constants.statistics import DdtmActivityGranularity
from core.permissions.scope import resolve_scoped_user_group
from core.services.ddtm_activity import DdtmActivityService
from core.utils.permissions import (
    DdtmGroupPermission,
    IsActiveAuthenticated,
    SupervisingGroupPermission,
)


def parse_granularity(request) -> str:
    """Read ?granularity= (MONTH default). 400 on an unknown value."""
    value = request.query_params.get("granularity", DdtmActivityGranularity.MONTH)
    if value not in DdtmActivityGranularity.values:
        raise ValidationError(
            f"Invalid granularity '{value}'. "
            f"Expected one of {DdtmActivityGranularity.values}."
        )
    return value


class DdtmActivityCommuneOptionSerializer(serializers.Serializer):
    uuid = serializers.UUIDField()
    name = serializers.CharField()


class DdtmActivityUserGroupOptionSerializer(serializers.Serializer):
    uuid = serializers.UUIDField()
    name = serializers.CharField()
    # Communes this group covers — backs the commune selector of the own-group and EPCI
    # dashboards. Empty for a DDTM caller, whose selector is over groups.
    communes = DdtmActivityCommuneOptionSerializer(many=True)


class DdtmActivitySummarySerializer(serializers.Serializer):
    # Exactly one of these two is set for a caller who SUPERVISES a territory, and both
    # are null for anyone else — that is what tells the client which dashboard to render:
    # department -> DDTM view, epci -> the same overview plus a commune selector,
    # neither -> the own-group view.
    department_name = serializers.CharField(allow_null=True)
    epci_name = serializers.CharField(allow_null=True)
    user_groups_count = serializers.IntegerField()
    active_user_groups_count = serializers.IntegerField()
    # (uuid, name) list for the section-2 group select.
    user_groups = DdtmActivityUserGroupOptionSerializer(many=True)


class DdtmActivityUserGroupSerializer(serializers.Serializer):
    uuid = serializers.UUIDField()
    name = serializers.CharField()
    users_count = serializers.IntegerField()
    active_users_count = serializers.IntegerField()
    pilot_users_count = serializers.IntegerField()
    # Deployment = earliest member first login; both null if none ever logged in.
    deployment_date = serializers.DateField(allow_null=True)
    deployed_since_weeks = serializers.IntegerField(allow_null=True)


class DdtmActivityUserSerializer(serializers.Serializer):
    uuid = serializers.UUIDField()
    email = serializers.EmailField()
    operational_actions_count = serializers.IntegerField()
    connections_count = serializers.IntegerField()
    # PILOT | RECURRENT | ACTIVE | INACTIVE over the 30-day window.
    activity_status = serializers.CharField()


class DdtmActivityPeriodTierSerializer(serializers.Serializer):
    # `period` is a period key: "YYYY-MM", "YYYY-Q<n>" or "YYYY-S<n>".
    period = serializers.CharField()
    pilot_count = serializers.IntegerField()
    recurrent_count = serializers.IntegerField()
    active_count = serializers.IntegerField()
    inactive_count = serializers.IntegerField()
    total_count = serializers.IntegerField()


class DdtmActivityStatusCountSerializer(serializers.Serializer):
    # `status` is a DetectionControlStatus value (a string value, not a key, so the
    # camelCase renderer leaves it intact).
    status = serializers.CharField()
    count = serializers.IntegerField()


class DdtmActivityControlStatusPeriodSerializer(serializers.Serializer):
    period = serializers.CharField()
    counts = DdtmActivityStatusCountSerializer(many=True)


class DdtmActivityCountPeriodSerializer(serializers.Serializer):
    period = serializers.CharField()
    count = serializers.IntegerField()


class DdtmActivityUserGroupActivitySerializer(serializers.Serializer):
    uuid = serializers.UUIDField()
    name = serializers.CharField()
    granularity = serializers.CharField()
    deployment_date = serializers.DateField(allow_null=True)
    # Period key containing the deployment (the chart's deployment marker).
    deployment_period = serializers.CharField(allow_null=True)
    # Last period key entirely before deployment (periods with no activity to show).
    no_data_until_period = serializers.CharField(allow_null=True)
    activity_by_period = DdtmActivityPeriodTierSerializer(many=True)
    control_status_changes_by_period = DdtmActivityControlStatusPeriodSerializer(
        many=True
    )
    report_downloads_by_period = DdtmActivityCountPeriodSerializer(many=True)
    connections_by_period = DdtmActivityCountPeriodSerializer(many=True)


class DdtmActivityGroupTiersSerializer(serializers.Serializer):
    uuid = serializers.UUIDField()
    name = serializers.CharField()
    # {period key: tier}. Periods where the group has no data yet are absent.
    tier_by_period = serializers.DictField(child=serializers.CharField())


class DdtmActivityGroupsActivitySerializer(serializers.Serializer):
    granularity = serializers.CharField()
    # Each collectivity group of the department classified into one tier per period.
    activity_by_period = DdtmActivityPeriodTierSerializer(many=True)
    # Same classification, per group — backs the per-category detail table.
    groups = DdtmActivityGroupTiersSerializer(many=True)


class StatisticsDdtmActivitySummaryView(APIView):
    """Dashboard header, and the endpoint that tells the client WHICH dashboard it may
    render: `departmentName` is the DDTM's department for a DDTM caller (department-wide
    view) and null for anyone else, who gets only the groups they belong to. Also the
    group count, how many are active (>= 1 member connected in the last 30 days) and the
    group list for the select. Stats cover non-staff users not belonging to a DDTM
    group."""

    permission_classes = [IsActiveAuthenticated]

    def get(self, request):
        summary = DdtmActivityService.get_summary(
            request.user, scoped_user_group=resolve_scoped_user_group(request)
        )
        serializer = DdtmActivitySummarySerializer(summary)
        return Response(serializer.data)


class StatisticsDdtmActivityUserGroupsView(APIView):
    """Per-group activity rows (counts) for the groups table, over the caller's
    supervised territory (a DDTM's department or an EPCI's communes). Served as a bare
    array so the frontend DataTable can consume it directly."""

    permission_classes = [SupervisingGroupPermission]

    def get(self, request):
        rows = DdtmActivityService.get_user_group_rows(
            request.user, scoped_user_group=resolve_scoped_user_group(request)
        )
        if rows is None:
            raise NotFound("No territory is linked to your group.")

        serializer = DdtmActivityUserGroupSerializer(rows, many=True)
        return Response(serializer.data)


class StatisticsDdtmActivityGroupsActivityView(APIView):
    """Territory-wide activity chart (a DDTM's department or an EPCI's communes): each
    collectivity group classified into one tier (pilot/active/connected/inactive) per
    period, at the requested granularity."""

    permission_classes = [SupervisingGroupPermission]

    def get(self, request):
        granularity = parse_granularity(request)
        activity = DdtmActivityService.get_groups_activity(
            request.user,
            granularity,
            scoped_user_group=resolve_scoped_user_group(request),
        )
        if activity is None:
            raise NotFound("No territory is linked to your group.")

        serializer = DdtmActivityGroupsActivitySerializer(activity)
        return Response(serializer.data)


class StatisticsDdtmActivityUserGroupUsersView(APIView):
    """Per-user activity rows for one group of the DDTM's department (the group-detail
    table). Served as a bare array for the frontend DataTable."""

    permission_classes = [DdtmGroupPermission]

    def get(self, request, uuid):
        users = DdtmActivityService.get_user_group_users(
            request.user, uuid, scoped_user_group=resolve_scoped_user_group(request)
        )
        if users is None:
            raise NotFound("User group not found in your department.")

        serializer = DdtmActivityUserSerializer(users, many=True)
        return Response(serializer.data)


class StatisticsDdtmActivityUserGroupView(APIView):
    """Per-period charts for one user group, at the requested granularity (each member
    classified into one tier per period).

    The only read path open to non-DDTM members, so that a collectivity can follow its
    own activity. Which groups the caller may read is decided by the service
    (DdtmActivityService._get_scoped_group): a DDTM member reads any collectivity group
    of their department, anyone else only their own groups — any other uuid is a 404.
    The per-user detail of a group stays DDTM-only
    (StatisticsDdtmActivityUserGroupUsersView)."""

    permission_classes = [IsActiveAuthenticated]

    def get(self, request, uuid):
        granularity = parse_granularity(request)
        activity = DdtmActivityService.get_user_group_activity(
            request.user,
            uuid,
            granularity,
            scoped_user_group=resolve_scoped_user_group(request),
        )
        if activity is None:
            raise NotFound("User group not found in your department.")

        serializer = DdtmActivityUserGroupActivitySerializer(activity)
        return Response(serializer.data)
