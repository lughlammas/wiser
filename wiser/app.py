"""Servidor do WISER (FastAPI). Rodar: python -m wiser.app  -> http://127.0.0.1:8765"""
from __future__ import annotations
import os, re, threading, time
from collections import Counter
from pathlib import Path
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import export, store
from .ingest import ACCEPTED, IngestError, ingest, sections
from .providers import ProviderError, ProviderUnavailable, chunk, get_provider, lang_code

def _load_env():
    f = Path(__file__).resolve().parent.parent / ".env"
    if f.exists():
        for l in f.read_text().splitlines():
            if "=" in l and not l.lstrip().startswith("#"):
                k, v = l.split("=", 1); os.environ.setdefault(k.strip(), v.strip())


_load_env()
STATIC = Path(__file__).parent / "static"
MAX_BYTES = 20 * 1024 * 1024
LANGS = ["Português", "Inglês", "Espanhol", "Francês", "Alemão", "Italiano", "Holandês", "Russo", "Polonês",
         "Ucraniano", "Turco", "Grego", "Hebraico", "Árabe", "Hindi", "Japonês", "Coreano", "Chinês", "Sueco", "Catalão"]
app = FastAPI(title="WISER")
_jobs: dict[str, threading.Thread] = {}


def _get(pid):
    try:
        return store.load(pid)
    except KeyError:
        raise HTTPException(404, "Projeto não encontrado.")


def _view(p):
    p = dict(p); p["sections"] = sections(p["blocks"])
    return p


@app.get("/api/languages")
def languages():
    return {"languages": LANGS, "accepted": list(ACCEPTED.values())}


@app.get("/api/status")
def status(src: str = "Português", tgt: str = "Inglês"):
    _, st = get_provider(lang_code(src), lang_code(tgt))
    st["src_code"], st["tgt_code"] = lang_code(src), lang_code(tgt)
    return st


@app.get("/api/projects")
def projects():
    return {"projects": store.listing()}


@app.post("/api/projects")
async def create(name: str = Form(""), text: str = Form(None), file: UploadFile = File(None)):
    try:
        if file is not None and file.filename:
            data = await file.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise IngestError("Arquivo grande demais (limite de 20 MB).")
            blocks, warns, kind = ingest(file.filename, data)
            p = store.create(name or file.filename.rsplit(".", 1)[0], blocks, warns, kind, file.filename, data)
        elif text:
            blocks, warns, kind = ingest(None, text=text)
            p = store.create(name or "Texto colado", blocks, warns, kind)
        else:
            raise IngestError("Envie um arquivo ou cole um texto.")
    except IngestError as e:
        raise HTTPException(400, str(e))
    return _view(p)


@app.get("/api/projects/{pid}")
def project(pid: str):
    return _view(_get(pid))


class Settings(BaseModel):
    name: str | None = None
    settings: dict | None = None
    step: int | None = None


@app.patch("/api/projects/{pid}")
def update(pid: str, body: Settings):
    p = _get(pid)
    if body.name:
        p["name"] = body.name[:200]
    if body.settings:
        allowed = {"src", "tgt", "style", "audience", "region", "tone", "keep_references", "keep_quotes"}
        for k, v in body.settings.items():
            if k in allowed:
                p["settings"][k] = v
        if p["settings"].get("style") not in ("fiel", "natural", "local"):
            p["settings"]["style"] = "natural"
    if body.step:
        p["step"] = max(1, min(5, body.step))
    store.save(p)
    return _view(p)


class Glossary(BaseModel):
    entries: list[dict]


@app.put("/api/projects/{pid}/glossary")
def glossary(pid: str, body: Glossary):
    p = _get(pid)
    p["glossary"] = [{"source": str(e.get("source", "")).strip()[:200], "target": str(e.get("target", "")).strip()[:200],
                      "keep": bool(e.get("keep")), "note": str(e.get("note", ""))[:500]}
                     for e in body.entries if str(e.get("source", "")).strip()]
    store.save(p)
    return {"glossary": p["glossary"]}


@app.get("/api/projects/{pid}/glossary/suggest")
def suggest(pid: str):
    """Candidatos: palavras com inicial maiúscula fora do início de frase, recorrentes. Só sugestão."""
    p = _get(pid)
    c = Counter()
    for b in p["blocks"]:
        for m in re.finditer(r"(?<=[\w,;:()] )([A-ZÁÉÍÓÚÂÊÔÃÕÇ][\wáéíóúâêôãõç'-]+(?: [A-Z][\w'-]+)*)", b["text"]):
            c[m.group(1)] += 1
    have = {g["source"] for g in p["glossary"]}
    return {"suggestions": [w for w, n in c.most_common(40) if n >= 2 and w not in have]}


def _run(pid):
    p = store.load(pid)
    s = p["settings"]
    src, tgt = lang_code(s["src"]), lang_code(s["tgt"])
    prov, st = get_provider(src, tgt)
    if not prov:
        p["job"] = {"state": "blocked", "status": st}; store.save(p); return
    todo = [b for b in p["blocks"] if b["id"] not in p["adaptation"]]
    parts = chunk(todo, int(os.environ.get("WISER_CHUNK_CHARS", "900")))
    p["job"] = {"state": "running", "provider": st["label"], "done": 0, "total": len(parts), "started": time.time()}
    store.save(p)
    ctx = {"src": src, "tgt": tgt, "src_name": s["src"], "tgt_name": s["tgt"], "style": s["style"],
           "audience": s.get("audience"), "region": s.get("region"), "tone": s.get("tone"),
           "keep_references": s.get("keep_references", True), "glossary": p["glossary"]}
    try:
        for i, part in enumerate(parts):
            res = prov.translate_chunk(part, ctx)
            p = store.load(pid)
            for r in res:  # mesma ordem e ids dos blocos originais
                p["adaptation"][r["id"]] = {"text": r["text"], "flags": r["flags"], "edited": False, "provider": prov.name}
            p["job"]["done"] = i + 1
            store.save(p)
        p = store.load(pid)
        note = [] if prov.applies_style else [
            "O tradutor local não aplica estilo, público, região nem tom: o resultado é uma tradução direta. Revise para chegar ao estilo escolhido."]
        p["job"] = {"state": "done", "provider": st["label"], "notes": note, "finished": time.time()}
        p["step"] = 4
        store.save(p)
    except (ProviderError, ProviderUnavailable, OSError, ValueError, KeyError) as e:
        p = store.load(pid)
        p["job"] = {"state": "error", "kind": getattr(e, "kind", "geracao"), "message": f"A adaptação parou: {e}. O que já foi feito está salvo; tente continuar."}
        store.save(p)


@app.post("/api/projects/{pid}/adapt")
def adapt(pid: str, redo: bool = False):
    p = _get(pid)
    s = p["settings"]
    if not s.get("tgt"):
        raise HTTPException(400, "Escolha o idioma de destino.")
    prov, st = get_provider(lang_code(s["src"]), lang_code(s["tgt"]))
    if not prov:
        p["job"] = {"state": "blocked", "status": st}; store.save(p)
        return JSONResponse(status_code=503, content={"detail": "Provedor de IA indisponível.", "status": st})
    t = _jobs.get(pid)
    if t and t.is_alive():
        return {"started": False, "job": p["job"]}
    if redo:
        p["adaptation"] = {k: v for k, v in p["adaptation"].items() if v.get("edited")}
        store.save(p)
    t = threading.Thread(target=_run, args=(pid,), daemon=True); _jobs[pid] = t; t.start()
    return {"started": True}


class Edit(BaseModel):
    text: str


@app.put("/api/projects/{pid}/blocks/{bid}")
def edit(pid: str, bid: str, body: Edit):
    p = _get(pid)
    if bid not in {b["id"] for b in p["blocks"]}:
        raise HTTPException(404, "Trecho não encontrado.")
    a = p["adaptation"].setdefault(bid, {"flags": [], "provider": "manual"})
    a["text"], a["edited"] = body.text, True
    store.save(p)
    return a


@app.post("/api/projects/{pid}/blocks/{bid}/flags/{n}/resolve")
def resolve(pid: str, bid: str, n: int):
    p = _get(pid)
    try:
        p["adaptation"][bid]["flags"][n]["resolved"] = True
    except (KeyError, IndexError):
        raise HTTPException(404, "Sinalização não encontrada.")
    store.save(p)
    return {"ok": True}


@app.get("/api/projects/{pid}/export.{fmt}")
def do_export(pid: str, fmt: str):
    p = _get(pid)
    miss = export.missing(p)
    if miss:
        raise HTTPException(409, f"Ainda há {len(miss)} trecho(s) sem adaptação. Conclua antes de exportar.")
    base = re.sub(r"[^\w\-]+", "_", p["name"])[:60] or "wiser"
    if fmt == "md":
        data, mt = export.to_markdown(p).encode("utf-8"), "text/markdown; charset=utf-8"
    elif fmt == "docx":
        data, mt = export.to_docx(p), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        raise HTTPException(404, "Formato desconhecido.")
    fn = f"{base}_{lang_code(p['settings']['tgt']) or 'adaptado'}.{fmt}"
    (store.export_dir(pid) / fn).write_bytes(data)
    return Response(data, media_type=mt, headers={"Content-Disposition": f'attachment; filename="{fn}"'})


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")


def main():
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("WISER_PORT", "8765")))


if __name__ == "__main__":
    main()
