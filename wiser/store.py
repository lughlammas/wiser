"""Persistência local em JSON (data/projects/<id>/). O original é guardado como cópia somente-leitura."""
from __future__ import annotations
import json, os, re, stat, threading, time, uuid
from pathlib import Path

ROOT = Path(os.environ.get("WISER_DATA", Path(__file__).resolve().parent.parent / "data")) / "projects"
_lock = threading.Lock()


def _dir(pid):
    if not re.fullmatch(r"[a-f0-9]{12}", pid or ""):
        raise KeyError(pid)
    return ROOT / pid


def create(name, blocks, warnings, kind, original_name=None, original_bytes=None):
    pid = uuid.uuid4().hex[:12]
    d = _dir(pid); (d / "exports").mkdir(parents=True)
    d.chmod(0o700)
    if original_bytes is not None:
        safe = re.sub(r"[^\w.\-]+", "_", original_name or "original")
        f = d / ("original_" + safe)
        f.write_bytes(original_bytes); f.chmod(stat.S_IRUSR)
    p = {"id": pid, "name": name, "created": time.time(), "updated": time.time(), "source_kind": kind,
         "original_file": original_name, "warnings": warnings, "blocks": blocks,
         "settings": {"src": "Português", "tgt": "", "style": "natural", "audience": "", "region": "",
                      "tone": "", "keep_references": True, "keep_quotes": False},
         "glossary": [], "adaptation": {}, "job": {"state": "idle"}, "step": 2}
    save(p)
    return p


def save(p):
    with _lock:
        p["updated"] = time.time()
        d = _dir(p["id"]); tmp = d / "project.json.tmp"
        tmp.write_text(json.dumps(p, ensure_ascii=False, indent=1), "utf-8")
        tmp.replace(d / "project.json")


def load(pid):
    f = _dir(pid) / "project.json"
    if not f.exists():
        raise KeyError(pid)
    return json.loads(f.read_text("utf-8"))


def listing():
    if not ROOT.exists():
        return []
    out = []
    for f in ROOT.glob("*/project.json"):
        p = json.loads(f.read_text("utf-8"))
        done = sum(1 for b in p["blocks"] if b["id"] in p["adaptation"])
        out.append({"id": p["id"], "name": p["name"], "updated": p["updated"], "tgt": p["settings"].get("tgt"),
                    "progress": f"{done}/{len(p['blocks'])}", "step": p.get("step", 2)})
    return sorted(out, key=lambda x: -x["updated"])


def export_dir(pid):
    return _dir(pid) / "exports"


def delete(pid):
    """Remove o projeto inteiro: dados, cópia do original e exportações. Só arquivos locais."""
    import shutil
    d = _dir(pid)
    if not (d / "project.json").exists():
        raise KeyError(pid)
    for f in d.rglob("*"):
        if f.is_file():
            f.chmod(0o600)
    with _lock:
        shutil.rmtree(d)
    return not d.exists()
