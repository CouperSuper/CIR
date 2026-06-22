from __future__ import annotations

import html
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


SHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def _column_name(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _safe_sheet_name(name: str) -> str:
    cleaned = re.sub(r"[\[\]:*?/\\]", "_", name)
    return cleaned[:31] or "Sheet"


def _cell_xml(value: Any, row_number: int, column_number: int) -> str:
    ref = f"{_column_name(column_number)}{row_number}"
    text = "" if value is None else str(value)
    return (
        f'<c r="{ref}" t="inlineStr"><is><t>{html.escape(text)}</t></is></c>'
    )


def _sheet_xml(rows: list[list[Any]]) -> str:
    row_xml = []
    for row_index, row in enumerate(rows, start=1):
        cells = "".join(_cell_xml(value, row_index, col_index) for col_index, value in enumerate(row, start=1))
        row_xml.append(f'<row r="{row_index}">{cells}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<worksheet xmlns="{SHEET_NS}"><sheetData>{"".join(row_xml)}</sheetData></worksheet>'
    )


def write_xlsx(path: Path, sheets: dict[str, list[list[Any]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet_names = [_safe_sheet_name(name) for name in sheets.keys()]
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            + "".join(
                f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                for i in range(1, len(sheet_names) + 1)
            )
            + "</Types>",
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="{PKG_REL_NS}">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>",
        )
        archive.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<workbook xmlns="{SHEET_NS}" xmlns:r="{REL_NS}"><sheets>'
            + "".join(
                f'<sheet name="{html.escape(name)}" sheetId="{i}" r:id="rId{i}"/>'
                for i, name in enumerate(sheet_names, start=1)
            )
            + "</sheets></workbook>",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="{PKG_REL_NS}">'
            + "".join(
                f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
                for i in range(1, len(sheet_names) + 1)
            )
            + "</Relationships>",
        )
        for index, rows in enumerate(sheets.values(), start=1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", _sheet_xml(rows))


def read_sheet(path: Path, sheet_name: str) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with zipfile.ZipFile(path, "r") as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_targets = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}
        target = ""
        for sheet in workbook.findall(f"{{{SHEET_NS}}}sheets/{{{SHEET_NS}}}sheet"):
            if sheet.attrib.get("name") == sheet_name:
                target = rel_targets.get(sheet.attrib.get(f"{{{REL_NS}}}id", ""), "")
                break
        if not target:
            return []
        sheet_xml = ET.fromstring(archive.read(f"xl/{target}"))

    rows: list[list[str]] = []
    for row in sheet_xml.findall(f"{{{SHEET_NS}}}sheetData/{{{SHEET_NS}}}row"):
        values: list[str] = []
        for cell in row.findall(f"{{{SHEET_NS}}}c"):
            text_node = cell.find(f"{{{SHEET_NS}}}is/{{{SHEET_NS}}}t")
            values.append(text_node.text if text_node is not None and text_node.text is not None else "")
        rows.append(values)
    if not rows:
        return []
    headers = rows[0]
    result = []
    for row in rows[1:]:
        padded = row + [""] * (len(headers) - len(row))
        result.append(dict(zip(headers, padded)))
    return result
