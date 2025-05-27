import zipfile
import tempfile
from pathlib import Path
from typing import Dict, Any


class ODTTemplateProcessor:
    def __init__(self, template_path: str):
        self.template_path = template_path

    def replace_placeholders(
        self, replacements: Dict[str, Any], output_path: str
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            with zipfile.ZipFile(self.template_path, "r") as zip_ref:
                zip_ref.extractall(temp_path)

            content_file = temp_path / "content.xml"
            if content_file.exists():
                self._process_xml_file(content_file, replacements)

            styles_file = temp_path / "styles.xml"
            if styles_file.exists():
                self._process_xml_file(styles_file, replacements)

            self._create_odt_file(temp_path, output_path)

    def _process_xml_file(self, xml_file: Path, replacements: Dict[str, Any]) -> None:
        with open(xml_file, "r", encoding="utf-8") as f:
            content = f.read()

        for placeholder, value in replacements.items():
            content = content.replace("{{" + placeholder + "}}", str(value))
            content = content.replace(placeholder, str(value))

        with open(xml_file, "w", encoding="utf-8") as f:
            f.write(content)

    def _create_odt_file(self, source_dir: Path, output_path: str) -> None:
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for file_path in source_dir.rglob("*"):
                if file_path.is_file():
                    relative_path = file_path.relative_to(source_dir)
                    zip_file.write(file_path, relative_path)
