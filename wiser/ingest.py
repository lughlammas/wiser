"""Ingestão: texto colado, TXT, MD, DOCX, PDF -> blocos estruturados.

Bloco: {"id", "type", "level", "text"}; type em
heading | paragraph | list_item | quote | note | reference.
Nunca altera o arquivo de origem (só lê bytes).
"""
from __future__ import annotations
import io, re, shutil, subprocess, tempfile
from collections import Counter

ACCEPTED = {".txt": "Texto (.txt)", ".md": "Markdown (.md)", ".markdown": "Markdown (.md)",
            ".docx": "Word (.docx)", ".pdf": "PDF (.pdf)"}
BIDI = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069]")
REF_HEAD = re.compile(r"^(refer[eê]ncias|bibliografia|references|bibliography|fontes)\b", re.I)
NOTE_HEAD = re.compile(r"^(notas?|notes?)\b", re.I)
NUM = re.compile(r"^(\d{1,3})[.)]\s+(.*)$")
BULLET = re.compile(r"^[-*•–]\s+(.*)$")


class IngestError(ValueError):
    pass


def _b(t, text, level=0):
    return {"type": t, "level": level, "text": text.strip()}


def _finish(blocks):
    """Ajusta tipos dentro de seções de referências/notas e numera ids."""
    out, mode = [], None
    for b in blocks:
        if not b["text"]:
            continue
        if b["type"] == "heading":
            mode = "reference" if REF_HEAD.match(b["text"]) else "note" if NOTE_HEAD.match(b["text"]) else None
        elif mode == "reference" and b["type"] == "paragraph":
            b["type"] = "note" if re.match(r"^nota\b", b["text"], re.I) else "reference"
        elif mode == "note" and b["type"] == "paragraph":
            b["type"] = "note"
        if b["type"] == "paragraph" and re.match(r"^(nota|note)\s*[:.]", b["text"], re.I):
            b["type"] = "note"
        out.append(b)
    for i, b in enumerate(out):
        b["id"] = f"b{i:04d}"
    return out


def parse_markdown(text: str):
    blocks, para = [], []
    def flush():
        if para:
            blocks.append(_b("paragraph", " ".join(para))); para.clear()
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        s = line.strip()
        if not s:
            flush(); continue
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            flush(); blocks.append(_b("heading", m.group(2), len(m.group(1)))); continue
        if s.startswith(">"):
            flush(); blocks.append(_b("quote", s.lstrip("> "))); continue
        m = re.match(r"^\[\^?[\w-]+\]:\s*(.*)$", s)
        if m:
            flush(); blocks.append(_b("note", s)); continue
        m = BULLET.match(s) or (NUM.match(s) and re.match(r"^\d+[.)]\s+", s))
        if m:
            flush(); blocks.append(_b("list_item", s)); continue
        para.append(s)
    flush()
    return _finish(blocks)


def parse_plain(text: str):
    """Texto simples / extraído de PDF: heurística de linhas."""
    text = BIDI.sub("", text).replace("\r\n", "\n")
    text = re.sub(r"\(\s*\)\s*([\u0590-\u05ff]+)", r"(\1)", text)
    text = re.sub(r"\(\s*([\u0590-\u05ff]+)\s*\)", r"(\1)", text)
    lines = [l.strip() for l in text.split("\n")]
    seen_heading = False
    blocks, para = [], []
    def flush():
        if para:
            blocks.append(_b("paragraph", " ".join(para))); para.clear()
    for i, s in enumerate(lines):
        if not s:
            flush(); continue
        m = NUM.match(s)
        short = len(s) < 70 and not s.endswith((".", ":", ";", ","))
        if m and short and m.group(2)[:1].isupper():
            flush(); blocks.append(_b("heading", s, 2)); seen_heading = True; continue
        if not seen_heading and not para and blocks and blocks[-1]["type"] == "heading" and s[:1].islower() and len(s) < 45:
            blocks[-1]["text"] += " " + s; continue
        if not seen_heading and short and len(s) < 45 and not para:
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if not nxt or len(nxt) < 45:
                blocks.append(_b("heading", s, 1)); continue
        if (REF_HEAD.match(s) or NOTE_HEAD.match(s)) and short:
            flush(); blocks.append(_b("heading", s, 2)); continue
        if m or BULLET.match(s):
            flush(); blocks.append(_b("list_item", s)); continue
        if s.startswith(("“", '"', "«")) and para == []:
            blocks.append(_b("quote", s)); continue
        if para and blocks and blocks[-1]["type"] == "list_item" and not para:
            pass
        # continuação de item de lista quebrado em linhas
        if not para and blocks and blocks[-1]["type"] == "list_item" and (
                s[:1].islower() or not blocks[-1]["text"].endswith((".", "!", "?", ":"))):
            blocks[-1]["text"] += " " + s; continue
        para.append(s)
        if len(s) < 80 and s.endswith((".", "?", "!", ":")):
            flush()
    flush()
    return _finish(blocks)


def _strip_repeated(pages: list[str]):
    """Remove cabeçalhos/rodapés repetidos e números de página."""
    cnt = Counter()
    for p in pages:
        cnt.update({l.strip() for l in p.split("\n") if l.strip()})
    rep = {l for l, c in cnt.items() if len(pages) > 2 and c >= max(3, len(pages) * 0.6)}
    out = []
    for p in pages:
        keep = [l for l in p.split("\n") if l.strip() not in rep and not re.fullmatch(r"\s*\d{1,4}\s*", l)]
        out.append("\n".join(keep))
    return out, sorted(rep)


def _pdf(data: bytes):
    warnings = []
    pages = None
    if shutil.which("pdftotext"):
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            f.write(data); f.flush()
            r = subprocess.run(["pdftotext", "-enc", "UTF-8", f.name, "-"], capture_output=True)
            if r.returncode == 0:
                pages = r.stdout.decode("utf-8", "replace").split("\f")
    from pypdf import PdfReader
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as e:
        raise IngestError(f"Não foi possível abrir o PDF: {e}")
    if reader.is_encrypted:
        raise IngestError("O PDF está protegido por senha. Remova a proteção e tente de novo.")
    if pages is None:
        pages = [(p.extract_text() or "") for p in reader.pages]
    pages = [p for p in pages if p is not None]
    imgs = 0
    for i, p in enumerate(reader.pages):
        try:
            n = len(p.images)
        except Exception:
            n = 0
        imgs += n
        if i < len(pages) and n and len(pages[i].strip()) < 30:
            warnings.append(f"A página {i+1} parece ser só imagem: o texto dela não pôde ser extraído.")
    if imgs:
        warnings.append(f"O PDF contém {imgs} imagem(ns). Texto dentro de imagens não é extraído.")
    pages, rep = _strip_repeated(pages)
    if rep:
        warnings.append("Cabeçalhos/rodapés repetidos foram omitidos da adaptação: " + "; ".join(rep[:4]))
    warnings.append("PDF não guarda a estrutura do texto: títulos, listas e parágrafos foram deduzidos. Confira na revisão.")
    text = "\n\n".join(pages)
    if not text.strip():
        raise IngestError("Nenhum texto pôde ser extraído deste PDF (talvez seja digitalizado como imagem).")
    if BIDI.search(text) or re.search(r"[\u0590-\u05ff\u0600-\u06ff]", text):
        warnings.append("Há trechos em escrita da direita para a esquerda (ex.: hebraico). Eles são mantidos como no original; confira a posição.")
    return parse_plain(text), warnings


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _numfmt(d):
    """numId -> {ilvl: numFmt} a partir de numbering.xml."""
    try:
        root = d.part.numbering_part.element
    except (KeyError, AttributeError, NotImplementedError):
        return {}
    absf = {}
    for an in root.findall(W + "abstractNum"):
        lv = {}
        for l in an.findall(W + "lvl"):
            f = l.find(W + "numFmt")
            lv[int(l.get(W + "ilvl"))] = f.get(W + "val") if f is not None else "decimal"
        absf[an.get(W + "abstractNumId")] = lv
    out = {}
    for n in root.findall(W + "num"):
        ref = n.find(W + "abstractNumId")
        out[n.get(W + "numId")] = absf.get(ref.get(W + "val") if ref is not None else "", {})
    return out


def _roman(n):
    vals = [(1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"), (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")]
    r = ""
    for v, sym in vals:
        while n >= v:
            r += sym; n -= v
    return r


def _marker(fmt, n):
    if fmt == "bullet" or fmt == "none":
        return "-"
    if fmt in ("lowerLetter", "upperLetter"):
        c = chr(ord("a") + (n - 1) % 26)
        return (c.upper() if fmt == "upperLetter" else c) + ")"
    if fmt in ("lowerRoman", "upperRoman"):
        r = _roman(n)
        return (r.upper() if fmt == "upperRoman" else r) + "."
    return f"{n}."


def _docx(data: bytes):
    """Importa DOCX preservando numeração e marcadores de listas (como texto literal)
    e lista explicitamente o que foi detectado e NÃO importado."""
    import docx
    try:
        d = docx.Document(io.BytesIO(data))
    except Exception as e:
        raise IngestError(f"Não foi possível abrir o DOCX: {e}")
    fmts = _numfmt(d)
    counters: dict = {}
    warnings, blocks = [], []
    for p in d.paragraphs:
        st = (p.style.name or "").lower() if p.style is not None else ""
        t = p.text.strip()
        if not t:
            continue
        ppr = p._p.pPr
        num = ppr.numPr if ppr is not None else None
        nid = num.numId.val if num is not None and num.numId is not None else None
        if nid is None and p.style is not None and p.style.element.pPr is not None and p.style.element.pPr.numPr is not None:
            sn = p.style.element.pPr.numPr
            nid = sn.numId.val if sn.numId is not None else None
            lvl = sn.ilvl.val if sn.ilvl is not None else 0
        else:
            lvl = num.ilvl.val if num is not None and num.ilvl is not None else 0
        if nid not in (None, 0) and str(nid) in fmts or (nid not in (None, 0) and "list" in st):
            fmt = fmts.get(str(nid), {}).get(lvl, "bullet" if "bullet" in st else "decimal")
            key = (str(nid), lvl)
            for k in [k for k in counters if k[0] == str(nid) and k[1] > lvl]:
                del counters[k]
            counters[key] = counters.get(key, 0) + 1
            m = _marker(fmt, counters[key])
            b = _b("list_item", f"{m} {t}", lvl)
            b["list"] = {"kind": "bullet" if m == "-" else "number", "marker": m, "level": lvl}
            blocks.append(b); continue
        if st == "title":
            blocks.append(_b("heading", t, 1))
        elif st.startswith("heading"):
            lv = re.findall(r"\d", st)
            blocks.append(_b("heading", t, min(int(lv[0]) + 1 if lv else 2, 6)))
        elif "list bullet" in st:
            b = _b("list_item", "- " + t); b["list"] = {"kind": "bullet", "marker": "-", "level": 0}; blocks.append(b)
        elif "list number" in st:
            counters[("style", 0)] = counters.get(("style", 0), 0) + 1
            m = f"{counters[('style', 0)]}."
            b = _b("list_item", f"{m} {t}"); b["list"] = {"kind": "number", "marker": m, "level": 0}; blocks.append(b)
        elif "quote" in st or "citação" in st:
            blocks.append(_b("quote", t))
        else:
            blocks.append(_b("paragraph", t))
    body = d.element.body
    xml = d.element.xml
    unsupported = []
    for i, tb in enumerate(d.tables, 1):
        first = ""
        try:
            first = next((c.text.strip() for r in tb.rows for c in r.cells if c.text.strip()), "")
        except Exception:
            pass
        unsupported.append(f"Tabela {i} ({len(tb.rows)} linha(s){', começa com: “' + first[:40] + '”' if first else ''})")
    nfoot = xml.count("<w:footnoteReference")
    if nfoot:
        unsupported.append(f"{nfoot} nota(s) de rodapé")
    nend = xml.count("<w:endnoteReference")
    if nend:
        unsupported.append(f"{nend} nota(s) de fim")
    ntx = xml.count("<w:txbxContent")
    if ntx:
        unsupported.append(f"{ntx} caixa(s) de texto")
    nimg = len(d.inline_shapes) + xml.count("<wp:anchor")
    if nimg:
        unsupported.append(f"{nimg} imagem(ns)/forma(s) (texto dentro de imagens não é extraído)")
    ncom = xml.count("<w:commentReference")
    if ncom:
        unsupported.append(f"{ncom} comentário(s)")
    if "<m:oMath" in xml:
        unsupported.append(f"{xml.count('<m:oMath ') + xml.count('<m:oMath>')} equação(ões)")
    try:
        hf = sum(1 for s_ in d.sections for h in (s_.header, s_.footer) if not h.is_linked_to_previous and any(p.text.strip() for p in h.paragraphs))
    except Exception:
        hf = 0
    if hf:
        unsupported.append(f"{hf} cabeçalho(s)/rodapé(s) de página")
    for u in unsupported:
        warnings.append("Não importado: " + u + ".")
    return _finish(blocks), warnings, unsupported


def ingest(filename: str | None, data: bytes | None = None, text: str | None = None):
    """Retorna (blocks, warnings, kind)."""
    if text is not None:
        t = text.strip()
        if not t:
            raise IngestError("O texto colado está vazio.")
        md = bool(re.search(r"^#{1,6}\s", t, re.M))
        return (parse_markdown(t) if md else parse_plain(t)), [], "texto colado"
    name = (filename or "").lower()
    ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
    if ext not in ACCEPTED:
        raise IngestError("Formato não aceito. Use DOCX, PDF, Markdown (.md) ou TXT, ou cole o texto.")
    if not data:
        raise IngestError("O arquivo está vazio.")
    if ext == ".pdf":
        b, w = _pdf(data)
    elif ext == ".docx":
        b, w, _ = _docx(data)
    else:
        try:
            s = data.decode("utf-8")
        except UnicodeDecodeError:
            s = data.decode("latin-1"); w0 = ["O arquivo não estava em UTF-8; foi lido como Latin-1. Confira acentos."]
        else:
            w0 = []
        b = parse_markdown(s) if ext in (".md", ".markdown") else parse_plain(s)
        w = w0
    if not b:
        raise IngestError("Nenhum texto foi encontrado no arquivo.")
    return b, w, ACCEPTED[ext]


def sections(blocks):
    """Agrupa blocos em seções (por título)."""
    secs, cur = [], None
    for b in blocks:
        if b["type"] == "heading" or cur is None:
            cur = {"id": f"s{len(secs):03d}", "title": b["text"] if b["type"] == "heading" else "Início", "blocks": []}
            secs.append(cur)
        cur["blocks"].append(b["id"])
    return secs
