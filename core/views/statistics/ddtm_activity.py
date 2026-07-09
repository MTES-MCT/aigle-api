from rest_framework import serializers
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from core.constants.statistics import DdtmActivityGranularity
from core.services.ddtm_activity import DdtmActivityService
from core.utils.permissions import DdtmGroupPermission


def parse_granularity(request) -> str:
    """Read ?granularity= (MONTH default). 400 on an unknown value."""
    value = request.query_params.get("granularity", DdtmActivityGranularity.MONTH)
    if value not in DdtmActivityGranularity.values:
        raise ValidationError(
            f"Invalid granularity '{value}'. "
            f"Expected one of {DdtmActivityGranularity.values}."
        )
    return value


class DdtmActivityUserGroupOptionSerializer(serializers.Serializer):
    uuid = serializers.UUIDField()
    name = serializers.CharField()


class DdtmActivitySummarySerializer(serializers.Serializer):
    department_name = serializers.CharField()
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
    # Last period key entirely before deployment (grey "not deployed" zone boundary).
    no_data_until_period = serializers.CharField(allow_null=True)
    activity_by_period = DdtmActivityPeriodTierSerializer(many=True)
    control_status_changes_by_period = DdtmActivityControlStatusPeriodSerializer(
        many=True
    )
    report_downloads_by_period = DdtmActivityCountPeriodSerializer(many=True)
    connections_by_period = DdtmActivityCountPeriodSerializer(many=True)


class DdtmActivityGroupsActivitySerializer(serializers.Serializer):
    granularity = serializers.CharField()
    # Each collectivity group of the department classified into one tier per period.
    activity_by_period = DdtmActivityPeriodTierSerializer(many=True)


class StatisticsDdtmActivitySummaryView(APIView):
    """Activity dashboard header for DDTM members: the DDTM's department name, the
    number of collectivity groups linked to a commune of that department, how many of
    them are active (>= 1 member connected in the last 30 days), and the group list for
    the section-2 select. Stats cover non-staff users not belonging to a DDTM group."""

    permission_classes = [DdtmGroupPermission]

    def get(self, request):
        summary = DdtmActivityService.get_summary(request.user)
        if summary is None:
            raise NotFound("No department is linked to your DDTM group.")

        serializer = DdtmActivitySummarySerializer(summary)
        return Response(serializer.data)


class StatisticsDdtmActivityUserGroupsView(APIView):
    """Per-group activity rows (counts) for the groups table. Served as a bare array so
    the frontend DataTable can consume it directly."""

    permission_classes = [DdtmGroupPermission]

    def get(self, request):
        rows = DdtmActivityService.get_user_group_rows(request.user)
        if rows is None:
            raise NotFound("No department is linked to your DDTM group.")

        serializer = DdtmActivityUserGroupSerializer(rows, many=True)
        return Response(serializer.data)


class StatisticsDdtmActivityGroupsActivityView(APIView):
    """Department-wide activity chart: each collectivity group classified into one tier
    (pilot/active/connected/inactive) per period, at the requested granularity."""

    permission_classes = [DdtmGroupPermission]

    def get(self, request):
        granularity = parse_granularity(request)
        activity = DdtmActivityService.get_groups_activity(request.user, granularity)
        if activity is None:
            raise NotFound("No department is linked to your DDTM group.")

        serializer = DdtmActivityGroupsActivitySerializer(activity)
        return Response(serializer.data)


class StatisticsDdtmActivityUserGroupUsersView(APIView):
    """Per-user activity rows for one group of the DDTM's department (the group-detail
    table). Served as a bare array for the frontend DataTable."""

    permission_classes = [DdtmGroupPermission]

    def get(self, request, uuid):
        users = DdtmActivityService.get_user_group_users(request.user, uuid)
        if users is None:
            raise NotFound("User group not found in your department.")

        serializer = DdtmActivityUserSerializer(users, many=True)
        return Response(serializer.data)


class StatisticsDdtmActivityUserGroupView(APIView):
    """Per-period charts for one user group of the DDTM's department, at the requested
    granularity (each member classified into one tier per period)."""

    permission_classes = [DdtmGroupPermission]

    def get(self, request, uuid):
        granularity = parse_granularity(request)
        activity = DdtmActivityService.get_user_group_activity(
            request.user, uuid, granularity
        )
        if activity is None:
            raise NotFound("User group not found in your department.")

        serializer = DdtmActivityUserGroupActivitySerializer(activity)
        return Response(serializer.data)
