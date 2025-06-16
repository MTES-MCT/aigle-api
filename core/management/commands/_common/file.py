from typing import Dict, Tuple
import requests
import tempfile
import zipfile
from django.core.management.base import CommandError

from core.utils.logs_helpers import log_command_event


def log_event(info: str):
    log_command_event(command_name="utils: file", info=info)


def download_file(
    url: str, file_name: str
) -> Tuple[tempfile.TemporaryDirectory[str], str]:
    file_res = requests.get(url, stream=True)
    temp_dir = tempfile.TemporaryDirectory()

    if file_res.status_code == 200:
        file_path = f"{temp_dir.name}/{file_name}"

        with open(file_path, "wb") as file:
            file.write(file_res.content)
            log_event(f"FILE DOWNLOADED: {file_path}")
    else:
        raise CommandError(f"FAILED TO DOWNLOAD FILE FROM URL: {url}")

    return temp_dir, file_path


def download_json(url: str) -> Dict:
    json_res = requests.get(url)

    if json_res.status_code == 200:
        return json_res.json()

    raise CommandError(f"FAILED TO DOWNLOAD JSON FROM URL: {url}")


def extract_zip(file_path: str, output_dir: str):
    with zipfile.ZipFile(file_path, "r") as zip_ref:
        zip_ref.extractall(output_dir)
        log_event(f"ZIP EXTRACTED: {output_dir}")
