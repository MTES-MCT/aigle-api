from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from core.services.ddtm_activity import DdtmActivityService
from core.utils.permissions import DdtmGroupPermission


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
    activity_status = serializers.CharField()


class DdtmActivityMonthSerializer(serializers.Serializer):
    month = serializers.CharField()
    pilot_users_count = serializers.IntegerField()
    active_users_count = serializers.IntegerField()
    inactive_users_count = serializers.IntegerField()


class DdtmActivityStatusCountSerializer(serializers.Serializer):
    # `status` is a DetectionControlStatus value (a string value, not a key, so the
    # camelCase renderer leaves it intact).
    status = serializers.CharField()
    count = serializers.IntegerField()


class DdtmActivityControlStatusMonthSerializer(serializers.Serializer):
    month = serializers.CharField()
    counts = DdtmActivityStatusCountSerializer(many=True)


class DdtmActivityCountMonthSerializer(serializers.Serializer):
    month = serializers.CharField()
    count = serializers.IntegerField()


class DdtmActivityUserGroupMonthlySerializer(serializers.Serializer):
    uuid = serializers.UUIDField()
    name = serializers.CharField()
    months = DdtmActivityMonthSerializer(many=True)
    control_status_changes_by_month = DdtmActivityControlStatusMonthSerializer(
        many=True
    )
    report_downloads_by_month = DdtmActivityCountMonthSerializer(many=True)
    connections_by_month = DdtmActivityCountMonthSerializer(many=True)


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
    """Monthly breakdown (pilot/active/inactive members) for one user group of the
    DDTM's department."""

    permission_classes = [DdtmGroupPermission]

    def get(self, request, uuid):
        activity = DdtmActivityService.get_user_group_monthly_activity(
            request.user, uuid
        )
        if activity is None:
            raise NotFound("User group not found in your department.")

        serializer = DdtmActivityUserGroupMonthlySerializer(activity)
        return Response(serializer.data)
