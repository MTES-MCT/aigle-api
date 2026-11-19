from django.db.models import Value
from django.test import SimpleTestCase

from core.models.parcel import Parcel
from core.services.parcel_filter import ParcelFilterService


class ParcelFilterOrderingTests(SimpleTestCase):
    """The /table parcel list is paginated with limit/offset: its order must be total."""

    def _order_by(self, ordering):
        queryset = ParcelFilterService(user=None)._apply_ordering(
            # the list annotates it (with_details)
            Parcel.objects.annotate(detections_count=Value(0)),
            ordering,
        )
        return list(queryset.query.order_by)

    def test_no_ordering_falls_back_to_id(self):
        self.assertEqual(self._order_by(None), ["id"])

    def test_parcel_ordering_ends_with_id(self):
        self.assertEqual(self._order_by("parcel"), ["section", "num_parcel", "id"])
        self.assertEqual(self._order_by("-parcel"), ["-section", "-num_parcel", "id"])

    def test_detections_count_ordering_ends_with_id(self):
        self.assertEqual(
            self._order_by("-detectionsCount"), ["-detections_count", "id"]
        )

    def test_unknown_ordering_falls_back_to_id(self):
        self.assertEqual(self._order_by("unknown"), ["id"])
