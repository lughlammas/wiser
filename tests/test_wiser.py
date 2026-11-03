import io, json, os, hashlib
from pathlib import Path
import pytest

PDF = Path("/cursor/stores/store-1352803c-771a-4461-a003-689f19b8aea8/grok-bot/agents/5cfe2274-12f2-4f6d-8a3c-96d364df365d/attachments/01M6FA0WZ4JWC4812QWQ1TAEZG.pdf")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WISER_DATA", str(tmp_path))
    import importlib, wiser.store as st
    importlib.reload(st)
    import wiser.app as app
    importlib.reload(app)
    from fastapi.testclient import TestClient
    return TestClient(app.app), app


def test_markdown_structure():
    from wiser.ingest import ingest
    b, w, k = ingest("a.md", "# Título\n\n## Cap 1\n\nTexto.\n\n- item\n1. um\n\n> citação\n\n[^1]: nota\n\n## Referências\n\nAutor, Livro.".encode())
    assert [x["type"] for x in b] == ["heading", "heading", "paragraph", "list_item", "list_item", "quote", "note", "heading", "reference"]


def test_rejects_unknown_format():
    from wiser.ingest import ingest, IngestError
    with pytest.raises(IngestError):
        ingest("x.odt", b"abc")


def test_docx_roundtrip():
    import docx
    from wiser.ingest import ingest
    d = docx.Document(); d.add_heading("Capítulo", 1); d.add_paragraph("Olá."); d.add_paragraph("Uma citação", style="Quote")
    buf = io.BytesIO(); d.save(buf)
    b, w, k = ingest("m.docx", buf.getvalue())
    assert [x["type"] for x in b] == ["heading", "paragraph", "quote"]


@pytest.mark.skipif(not PDF.exists(), reason="PDF de teste ausente")
def test_pdf_test_manuscript():
    from wiser.ingest import ingest, sections
    before = hashlib.sha256(PDF.read_bytes()).hexdigest()
    b, w, k = ingest(PDF.name, PDF.read_bytes())
    heads = [x["text"] for x in b if x["type"] == "heading"]
    assert "1. O que são os 32 caminhos" in heads and "Referências e nota editorial" in heads
    assert sum(x["type"] == "list_item" for x in b) >= 30
    assert any(x["type"] == "reference" for x in b) and any(x["type"] == "note" for x in b)
    assert not any("CADERNO DE ESTUDO" in x["text"] for x in b)  # cabeçalho repetido removido
    assert any("(א)" in x["text"] for x in b)
    assert any("hebraico" in x for x in w)
    assert len(sections(b)) >= 10
    assert hashlib.sha256(PDF.read_bytes()).hexdigest() == before


def test_chunk_preserves_order():
    from wiser.providers import chunk
    blocks = [{"id": f"b{i}", "text": "x" * 400} for i in range(20)]
    parts = chunk(blocks, 1000)
    assert [b["id"] for p in parts for b in p] == [b["id"] for b in blocks]
    assert all(sum(len(b["text"]) for b in p) <= 1000 for p in parts)


def test_no_provider_never_fakes(client, monkeypatch):
    c, app = client
    monkeypatch.delenv("WISER_PROVIDER", raising=False)
    os.environ.pop("WISER_PROVIDER", None)
    p = c.post("/api/projects", data={"text": "Olá mundo.\n\nSegundo parágrafo."}).json()
    c.patch(f"/api/projects/{p['id']}", json={"settings": {"tgt": "Inglês"}})
    r = c.post(f"/api/projects/{p['id']}/adapt")
    assert r.status_code == 503 and r.json()["status"]["help"]["passos"]
    assert c.get(f"/api/projects/{p['id']}").json()["adaptation"] == {}
    assert c.get(f"/api/projects/{p['id']}/export.md").status_code == 409


def test_gemini_missing_key(monkeypatch):
    monkeypatch.setenv("WISER_PROVIDER", "gemini"); monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    from wiser.providers import get_provider
    p, st = get_provider("pt", "en")
    assert p is None and "GEMINI_API_KEY" in st["reasons"][0]


def test_ollama_unreachable(monkeypatch):
    monkeypatch.setenv("WISER_PROVIDER", "ollama"); monkeypatch.setenv("WISER_OLLAMA_URL", "http://127.0.0.1:9/v1")
    from wiser.providers import get_provider
    p, st = get_provider("pt", "en")
    assert p is None and "não está acessível" in st["reasons"][0]


def test_429_message(monkeypatch):
    import urllib.error, wiser.providers as pv
    def boom(*a, **k): raise urllib.error.HTTPError("u", 429, "x", {}, io.BytesIO(b""))
    monkeypatch.setattr(pv.urllib.request, "urlopen", boom)
    with pytest.raises(pv.ProviderError) as e:
        pv._http_json("http://x", {}, {})
    assert e.value.kind == "limite"


class FakeLLM:
    """Dublê de teste: devolve o texto marcado [EN]. Só usado nos testes."""
    name, label, applies_style, privacy = "fake", "fake", True, "teste"
    def available(self, s, t): return True, ""
    def translate_chunk(self, blocks, ctx):
        return [{"id": b["id"], "text": "[EN] " + b["text"], "flags": []} for b in blocks]


def test_full_flow_edit_glossary_export(client, monkeypatch):
    c, app = client
    monkeypatch.setattr(app, "get_provider", lambda s, t: (FakeLLM(), {"ok": True, "label": "fake", "applies_style": True}))
    p = c.post("/api/projects", files={"file": ("m.md", "# Livro\n\n## Um\n\nTexto de Keter.\n\n- item".encode())}).json()
    pid = p["id"]
    c.patch(f"/api/projects/{pid}", json={"settings": {"tgt": "Inglês", "style": "xx"}})
    assert c.get(f"/api/projects/{pid}").json()["settings"]["style"] == "natural"
    assert c.put(f"/api/projects/{pid}/glossary", json={"entries": [{"source": "Keter", "keep": True}, {"source": " "}]}).json()["glossary"] == [{"source": "Keter", "target": "", "keep": True, "note": ""}]
    assert c.post(f"/api/projects/{pid}/adapt").status_code == 200
    app._jobs[pid].join(5)
    j = c.get(f"/api/projects/{pid}").json()
    assert j["job"]["state"] == "done" and len(j["adaptation"]) == 4
    c.put(f"/api/projects/{pid}/blocks/b0002", json={"text": "Keter's text."})
    md = c.get(f"/api/projects/{pid}/export.md").text
    assert md.splitlines()[0] == "# [EN] Livro" and "Keter's text." in md
    d = c.get(f"/api/projects/{pid}/export.docx")
    assert d.status_code == 200 and d.content[:2] == b"PK"
    assert any(x["id"] == pid for x in c.get("/api/projects").json()["projects"])


def test_argos_glossary_and_protection():
    from wiser.providers import ArgosProvider
    a = ArgosProvider()
    if not a.available("pt", "en")[0]:
        pytest.skip("par pt-en do Argos não instalado")
    out = a.translate_chunk([{"id": "b1", "type": "paragraph", "text": "Aleph (א) pertence ao Sefer Yetzirah, ver https://x.org/a."}],
                            {"src": "pt", "tgt": "en", "glossary": [{"source": "Sefer Yetzirah", "keep": True}]})
    t = out[0]["text"]
    assert "(א)" in t and "Sefer Yetzirah" in t and "https://x.org/a" in t


def test_sanity_flags():
    from wiser.providers import sanity_flags
    assert sanity_flags("5. As sete letras-duplas", "Beth, Gimel and Tav are the seven doubles.")
    assert sanity_flags("Fato textual: o livro apresenta 32 caminhos.", "The book presents 32 paths.")
    assert not sanity_flags("1. Keter - Coroa.", "1. Keter - Crown.")
