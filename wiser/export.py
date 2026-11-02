"""Exportação DOCX e Markdown a partir da adaptação revisada (nunca do original)."""
from __future__ import annotations
import io, re


def _text(p, b):
    a = p["adaptation"].get(b["id"])
    return a["text"] if a else None


def missing(p):
    return [b["id"] for b in p["blocks"] if b["id"] not in p["adaptation"]]


def to_markdown(p):
    lines = []
    for b in p["blocks"]:
        t = _text(p, b)
        if t is None:
            continue
        if b["type"] == "heading":
            lines.append("#" * max(1, b["level"]) + " " + t)
        elif b["type"] == "list_item":
            lines.append(t if re.match(r"^(\d+[.)]|[-*•])\s", t) else "- " + t)
        elif b["type"] == "quote":
            lines.append("> " + t)
        elif b["type"] == "note":
            lines.append("*" + t + "*")
        else:
            lines.append(t)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def to_docx(p) -> bytes:
    import docx
    d = docx.Document()
    d.core_properties.title = p["name"]
    d.core_properties.language = p["settings"].get("tgt", "")
    for b in p["blocks"]:
        t = _text(p, b)
        if t is None:
            continue
        if b["type"] == "heading":
            d.add_heading(t, level=min(max(b["level"] - 1, 0), 9) if b["level"] else 1)
        elif b["type"] == "list_item":
            d.add_paragraph(t, style="List Paragraph" if re.match(r"^\d+[.)]\s", t) else "List Bullet")
        elif b["type"] == "quote":
            d.add_paragraph(t, style="Quote")
        elif b["type"] == "note":
            d.add_paragraph().add_run(t).italic = True
        else:
            d.add_paragraph(t)
    buf = io.BytesIO(); d.save(buf)
    return buf.getvalue()
