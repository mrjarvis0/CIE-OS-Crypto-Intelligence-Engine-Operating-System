"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.reporting.pdf

Purpose:
    PDF report rendering using stdlib only (no external dependencies).

    Produces a valid PDF 1.4 document with the report content rendered as
    plain text pages. The output is a real PDF that any viewer can open,
    not Markdown bytes masquerading as one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..schemas.report import IntelligenceReport


_FONT_SIZE = 10
_TITLE_SIZE = 16
_HEADING_SIZE = 13
_PAGE_WIDTH = 612
_PAGE_HEIGHT = 792
_MARGIN = 72
_LINE_HEIGHT = 14
_USABLE_WIDTH = _PAGE_WIDTH - 2 * _MARGIN
_LINES_PER_PAGE = (_PAGE_HEIGHT - 2 * _MARGIN) // _LINE_HEIGHT


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap(text: str, max_chars: int = 80) -> list[str]:
    lines: list[str] = []
    for raw_line in text.split("\n"):
        if not raw_line:
            lines.append("")
            continue
        while len(raw_line) > max_chars:
            brk = raw_line.rfind(" ", 0, max_chars)
            if brk <= 0:
                brk = max_chars
            lines.append(raw_line[:brk])
            raw_line = raw_line[brk:].lstrip()
        lines.append(raw_line)
    return lines


class PdfRenderer:
    """
    Renders an intelligence report to a valid PDF 1.4 document.

    Uses raw PDF syntax so no external library is required. The output
    is plain-text pages with Helvetica font — functional, not styled.
    """

    def render(self, report: IntelligenceReport) -> bytes:
        text_lines = self._report_to_lines(report)
        pages = self._paginate(text_lines)
        return self._build_pdf(pages, report.title)

    def _report_to_lines(self, report: IntelligenceReport) -> list[tuple[str, int]]:
        lines: list[tuple[str, int]] = []

        lines.append((report.title, _TITLE_SIZE))
        lines.append(("", _FONT_SIZE))
        lines.append((f"Report ID: {report.report_id}", _FONT_SIZE))
        lines.append((f"Generated: {report.created_at.strftime('%Y-%m-%d %H:%M UTC')}", _FONT_SIZE))
        lines.append(("", _FONT_SIZE))

        if report.summary:
            lines.append(("Executive Summary", _HEADING_SIZE))
            lines.append(("", _FONT_SIZE))
            for wrapped in _wrap(report.summary.headline):
                lines.append((wrapped, _FONT_SIZE))
            lines.append(("", _FONT_SIZE))
            for finding in report.summary.key_findings:
                for wrapped in _wrap(f"  - {finding}"):
                    lines.append((wrapped, _FONT_SIZE))
            if report.summary.bottom_line:
                lines.append(("", _FONT_SIZE))
                for wrapped in _wrap(f"Bottom line: {report.summary.bottom_line}"):
                    lines.append((wrapped, _FONT_SIZE))
            lines.append((f"Confidence: {report.summary.confidence:.0%}", _FONT_SIZE))
            lines.append(("", _FONT_SIZE))

        if report.scores:
            lines.append(("Scores", _HEADING_SIZE))
            lines.append(("", _FONT_SIZE))
            for s in report.scores:
                lines.append(
                    (f"  {s.name}: {s.value:.0f}/100 ({s.band}) confidence={s.confidence:.0%}", _FONT_SIZE)
                )
                for comp in s.components:
                    lines.append((f"    - {comp.name}: {comp.value:.1f} (weight {comp.weight:.1f})", _FONT_SIZE))
            lines.append(("", _FONT_SIZE))

        if report.evidence:
            lines.append(("Evidence", _HEADING_SIZE))
            lines.append(("", _FONT_SIZE))
            for artifact in report.evidence:
                for wrapped in _wrap(
                    f"  [{artifact.source_type}] {artifact.claim} "
                    f"(tier={artifact.tier}, confidence={artifact.confidence:.0%})"
                ):
                    lines.append((wrapped, _FONT_SIZE))
            lines.append(("", _FONT_SIZE))

        if report.sections:
            for section_name, section_data in report.sections.items():
                lines.append((section_name.replace("_", " ").title(), _HEADING_SIZE))
                lines.append(("", _FONT_SIZE))
                if isinstance(section_data, dict):
                    for k, v in section_data.items():
                        for wrapped in _wrap(f"  {k}: {v}"):
                            lines.append((wrapped, _FONT_SIZE))
                elif isinstance(section_data, list):
                    for item in section_data:
                        for wrapped in _wrap(f"  - {item}"):
                            lines.append((wrapped, _FONT_SIZE))
                else:
                    for wrapped in _wrap(f"  {section_data}"):
                        lines.append((wrapped, _FONT_SIZE))
                lines.append(("", _FONT_SIZE))

        return lines

    @staticmethod
    def _paginate(lines: list[tuple[str, int]]) -> list[list[tuple[str, int]]]:
        pages: list[list[tuple[str, int]]] = []
        current: list[tuple[str, int]] = []
        for line in lines:
            current.append(line)
            if len(current) >= _LINES_PER_PAGE:
                pages.append(current)
                current = []
        if current:
            pages.append(current)
        if not pages:
            pages.append([("(empty report)", _FONT_SIZE)])
        return pages

    @staticmethod
    def _build_pdf(pages: list[list[tuple[str, int]]], title: str) -> bytes:
        objects: list[bytes] = []
        offsets: list[int] = []

        def add_obj(data: str) -> int:
            obj_num = len(objects) + 1
            objects.append(data.encode("latin-1", errors="replace"))
            return obj_num

        catalog_id = add_obj("")
        pages_id = add_obj("")
        font_id = add_obj(
            f"{len(objects) + 1} 0 obj\n"
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\n"
            "endobj\n"
        )

        page_ids: list[int] = []
        for page_lines in pages:
            stream_parts: list[str] = ["BT\n"]
            y = _PAGE_HEIGHT - _MARGIN
            for text, size in page_lines:
                escaped = _pdf_escape(text)
                stream_parts.append(f"/F1 {size} Tf\n")
                stream_parts.append(f"{_MARGIN} {y} Td\n")
                stream_parts.append(f"({escaped}) Tj\n")
                y -= _LINE_HEIGHT
                if y < _MARGIN:
                    break
            stream_parts.append("ET\n")
            stream = "".join(stream_parts)

            content_id = add_obj(
                f"{len(objects) + 1} 0 obj\n"
                f"<< /Length {len(stream)} >>\n"
                f"stream\n{stream}endstream\n"
                "endobj\n"
            )

            page_id = add_obj(
                f"{len(objects) + 1} 0 obj\n"
                "<< /Type /Page "
                f"/Parent {pages_id} 0 R "
                f"/MediaBox [0 0 {_PAGE_WIDTH} {_PAGE_HEIGHT}] "
                f"/Contents {content_id} 0 R "
                f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
                ">>\n"
                "endobj\n"
            )
            page_ids.append(page_id)

        kids = " ".join(f"{pid} 0 R" for pid in page_ids)
        objects[pages_id - 1] = (
            f"{pages_id} 0 obj\n"
            f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>\n"
            "endobj\n"
        ).encode("latin-1")

        escaped_title = _pdf_escape(title)
        objects[catalog_id - 1] = (
            f"{catalog_id} 0 obj\n"
            f"<< /Type /Catalog /Pages {pages_id} 0 R >>\n"
            "endobj\n"
        ).encode("latin-1")

        output = bytearray()
        output.extend(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")

        for i, obj_data in enumerate(objects):
            offsets.append(len(output))
            if not obj_data.startswith(f"{i + 1} 0 obj".encode()):
                output.extend(f"{i + 1} 0 obj\n".encode())
                output.extend(obj_data)
                output.extend(b"\nendobj\n")
            else:
                output.extend(obj_data)

        xref_offset = len(output)
        output.extend(b"xref\n")
        output.extend(f"0 {len(objects) + 1}\n".encode())
        output.extend(b"0000000000 65535 f \n")
        for off in offsets:
            output.extend(f"{off:010d} 00000 n \n".encode())

        output.extend(b"trailer\n")
        output.extend(
            f"<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n".encode()
        )
        output.extend(b"startxref\n")
        output.extend(f"{xref_offset}\n".encode())
        output.extend(b"%%EOF\n")

        return bytes(output)
