"""Exportação DOCX e Markdown a partir da adaptação revisada (nunca do original).
Itens de lista mantêm o marcador/numeração do original."""
from __future__ import annotations
import io, re

MARK = re.compile(r"^\s*((?:\d+|[a-zA-Z]|[ivxlcdmIVXLCDM]+)[.)]|[-*•–])\s+")


def _text(p, b):
    a = p["adaptation"].get(b["id"])
    return a["text"] if a else None


def missing(p):
    return [b["id"] for b in p["blocks"] if b["id"] not in p["adaptation"]]


def list_parts(b, t):
    """(tipo, marcador, nível, texto sem marcador)."""
    meta = b.get("list") or {}
    m = MARK.match(b["text"])
    marker = meta.get("marker") or (m.group(1) if m else "-")
    if marker in ("*", "•", "–"):
        marker = "-"
    kind = meta.get("kind") or ("bullet" if marker == "-" else "number")
    body = MARK.sub("", t, count=1) if MARK.match(t) else t
    return kind, marker, int(meta.get("level", b.get("level", 0)) or 0), body.strip()


def to_markdown(p):
    lines = []
    for b in p["blocks"]:
        t = _text(p, b)
        if t is None:
            continue
        if b["type"] == "heading":
            lines.append("#" * max(1, b["level"]) + " " + t)
        elif b["type"] == "list_item":
            kind, marker, lvl, body = list_parts(b, t)
            lines.append("   " * lvl + f"{marker} {body}")
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
    from docx.shared import Cm
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
            kind, marker, lvl, body = list_parts(b, t)
            if kind == "bullet":
                para = d.add_paragraph(body, style="List Bullet" if lvl == 0 else f"List Bullet {min(lvl + 1, 3)}")
            else:  # numeração literal do original: não depende do renumerador do Word
                para = d.add_paragraph(f"{marker}\t{body}", style="List Paragraph")
                para.paragraph_format.left_indent = Cm(1.0 + 0.75 * lvl)
                para.paragraph_format.first_line_indent = Cm(-0.75)
        elif b["type"] == "quote":
            d.add_paragraph(t, style="Quote")
        elif b["type"] == "note":
            d.add_paragraph().add_run(t).italic = True
        else:
            d.add_paragraph(t)
    buf = io.BytesIO(); d.save(buf)
    return buf.getvalue()
