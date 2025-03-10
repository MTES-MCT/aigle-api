from datetime import datetime
import random
import re
from typing import Iterable, List, Optional, Tuple, TypedDict
from django.core.management.base import BaseCommand
import csv
from django.db.models import Q

from aigle.settings import PASSWORD_MIN_LENGTH
from core.models.user import User, UserRole
from core.utils.string import normalize, slugify

from core.models.detection_data import DetectionControlStatus
from core.models.parcel import Parcel
from core.models.user_group import UserGroup, UserGroupRight, UserUserGroup

DATE_FORMAT = "%d/%m/%Y"


STATUSES_MAP = {
    "Astreinte Administrative": DetectionControlStatus.ADMINISTRATIVE_CONSTRAINT,
    "Contrôlé terrain": DetectionControlStatus.CONTROLLED_FIELD,
    "PV dressé": DetectionControlStatus.OFFICIAL_REPORT_DRAWN_UP,
    "Remis en état": DetectionControlStatus.REHABILITATED,
}


class PvRow(TypedDict):
    COMMUNE: str
    CODE_INSEE: str
    REF_CADAST: str
    DATE_PV: Optional[str]
    DATE: Optional[str]
    USER_GROUP: Optional[str]
    STATUS: Optional[str]


class Command(BaseCommand):
    help = "Convert a shape to postgis geometry and insert it in database"

    def add_arguments(self, parser):
        parser.add_argument("--pv-csv-path", type=str, required=True)
        parser.add_argument("--with-user-group", type=bool, default=False)
        parser.add_argument("--with-status", type=bool, default=False)

    def handle(self, *args, **options):
        pv_csv_path = options["pv_csv_path"]
        with_user_group = options["with_user_group"]
        with_status = options["with_status"]

        if with_user_group:
            user_group_names = set()

            with open(pv_csv_path, mode="r") as csv_file:
                reader = csv.DictReader(csv_file, delimiter=",")

                for row in reader:
                    user_group_names.add(row["USER_GROUP"])

            get_and_create_users_last_update(user_group_names=user_group_names)

        csv_file = open(pv_csv_path)
        processed_count = {
            "parcels_found": 0,
            "parcels_not_found": 0,
            "detection_objects_updated": 0,
        }

        parcels_not_found = []

        reader = csv.DictReader(csv_file, delimiter=",")

        row: PvRow
        for row in reader:
            try:
                cadastre_letters, cadastre_numbers = split_cadast_ref(
                    cadast_ref=row["REF_CADAST"]
                )
            except ValueError:
                print(f"IMPORT PVS: REF_CADAST invalid: {row["REF_CADAST"]}")
                continue

            parcel = (
                Parcel.objects.filter(
                    Q(commune__iso_code=row["CODE_INSEE"])
                    | Q(commune__name_normalized=normalize(row["COMMUNE"]))
                )
                .filter(
                    section=cadastre_letters,
                    num_parcel=cadastre_numbers,
                )
                .prefetch_related(
                    "detection_objects",
                    "detection_objects__detections",
                    "detection_objects__detections__detection_data",
                )
                .first()
            )

            if not parcel:
                processed_count["parcels_not_found"] += 1
                parcels_not_found.append([row["CODE_INSEE"], row["REF_CADAST"]])
                print(
                    f"IMPORT PVS: parcel not found: code_insee={row["CODE_INSEE"]},ref_cadast={row["REF_CADAST"]} ; search_parameters: section={cadastre_letters},num_parcel={cadastre_numbers}"
                )
                continue

            processed_count["parcels_found"] += 1
            processed_count["detection_objects_updated"] += (
                parcel.detection_objects.count()
            )

            for detection_object in parcel.detection_objects.all():
                detection_control_status = None
                if with_status:
                    detection_control_status = STATUSES_MAP.get(row["STATUS"])
                detection_control_status = (
                    detection_control_status
                    or DetectionControlStatus.OFFICIAL_REPORT_DRAWN_UP
                )

                official_report_date = None
                if (
                    detection_control_status
                    == DetectionControlStatus.OFFICIAL_REPORT_DRAWN_UP
                ):
                    try:
                        official_report_date = datetime.strptime(
                            row.get("DATE_PV") or row.get("DATE"), DATE_FORMAT
                        )
                    except ValueError:
                        pass

                for detection in detection_object.detections.all():
                    if official_report_date:
                        detection.detection_data.official_report_date = (
                            official_report_date
                        )
                    detection.detection_data.detection_control_status = (
                        detection_control_status
                    )

                    detection.detection_data.save()

            print(
                f"IMPORT PVS: updating detections for parcel: {parcel.id_parcellaire}"
            )

        csv_file.close()

        csv_not_found_filename = f'import_pvs_parcels_not_found-{datetime.today().strftime('%Y-%m-%d-%H:%M:%S')}.csv'

        with open(csv_not_found_filename, "w", newline="") as csvfile:
            csv_not_found_writer = csv.writer(csvfile)
            csv_not_found_writer.writerow(["CODE_INSEE", "REF_CADAST"])

            for row in parcels_not_found:
                csv_not_found_writer.writerow(row)

        print("IMPORT PVS: FINISHED")
        print(f"IMPORT PVS: parcels not found={processed_count['parcels_not_found']}")
        print(f"IMPORT PVS: parcels found={processed_count['parcels_found']}")
        print(
            f"IMPORT PVS: objects updated={processed_count['detection_objects_updated']}"
        )
        print(f"IMPORT PVS: list of not found saved here={csv_not_found_filename}")


# utils


def get_and_create_users_last_update(user_group_names: Iterable[str]) -> List[User]:
    emails_user_group_names_map = {
        get_email_user_last_update(user_group_name): user_group_name
        for user_group_name in user_group_names
    }
    users = list(
        User.objects.filter(email__in=emails_user_group_names_map.keys()).all()
    )

    emails_found = [user.email for user in users]
    emails_not_found = list(set(emails_user_group_names_map.keys()) - set(emails_found))

    for email in emails_not_found:
        print(f"IMPORT PVS: creating user with email={email}")
        user = User.objects.create_user(
            email=email,
            password=generate_random_string(),
            user_role=UserRole.REGULAR,
        )

        user_group = UserGroup.objects.filter(
            name__icontains=emails_user_group_names_map[email]
        ).first()

        if user_group:
            user_user_group = UserUserGroup(
                user_group_rights=[
                    UserGroupRight.READ,
                    UserGroupRight.WRITE,
                    UserGroupRight.ANNOTATE,
                ],
                user=user,
                user_group=user_group,
            )
            user_user_group.save()

        users.append(user)

    return users


def generate_random_string():
    length = PASSWORD_MIN_LENGTH * 2

    chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*()-_=+[]{}|;:,.<>?"
    return "".join(random.choice(chars) for _ in range(length))


def get_email_user_last_update(user_group_name: str) -> str:
    return f"aigle+{slugify(user_group_name)}@beta.gouv.fr"


def split_cadast_ref(cadast_ref: str) -> Tuple[str, str]:
    cadast_ref_ = cadast_ref.lstrip("0")
    cadast_ref_ = cadast_ref_.replace(" ", "")
    match = re.match(r"([A-Za-z]+)(\d+)", cadast_ref_)
    if match:
        return match.group(1), str(int(match.group(2)))
    raise ValueError(f"Invalid format: {cadast_ref}")
