import io, json, os, hashlib
from pathlib import Path
import pytest

FIX = Path(__file__).parent / "fixtures"
PDF = FIX / "sintetico.pdf"


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


def test_pdf_fixture_structure():
    from wiser.ingest import ingest, sections
    before = hashlib.sha256(PDF.read_bytes()).hexdigest()
    b, w, k = ingest(PDF.name, PDF.read_bytes())
    heads = [x["text"] for x in b if x["type"] == "heading"]
    assert "1. Como preparar o solo" in heads and "Referências" in heads
    assert [x["text"][:2] for x in b if x["type"] == "list_item"] == ["1.", "2."]
    assert any(x["type"] == "reference" for x in b) and any(x["type"] == "note" for x in b)
    assert not any("CADERNO SINTÉTICO" in x["text"] for x in b)
    assert any("repetidos" in x for x in w)
    assert len(sections(b)) >= 4
    assert hashlib.sha256(PDF.read_bytes()).hexdigest() == before


def test_txt_hebrew_kept():
    from wiser.ingest import ingest
    b, w, k = ingest("t.txt", (FIX / "sintetico.txt").read_bytes())
    assert any("(א)" in x["text"] for x in b)


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
    p = c.post("/api/projects", files={"file": ("m.md", "# Livro\n\n## Um\n\nTexto de Mirela.\n\n- item".encode())}).json()
    pid = p["id"]
    c.patch(f"/api/projects/{pid}", json={"settings": {"tgt": "Inglês", "style": "xx"}})
    assert c.get(f"/api/projects/{pid}").json()["settings"]["style"] == "natural"
    assert c.put(f"/api/projects/{pid}/glossary", json={"entries": [{"source": "Mirela", "keep": True}, {"source": " "}]}).json()["glossary"] == [{"source": "Mirela", "target": "", "keep": True, "note": ""}]
    assert c.post(f"/api/projects/{pid}/adapt").status_code == 200
    app._jobs[pid].join(5)
    j = c.get(f"/api/projects/{pid}").json()
    assert j["job"]["state"] == "done" and len(j["adaptation"]) == 4
    c.put(f"/api/projects/{pid}/blocks/b0002", json={"text": "Mirela's text."})
    md = c.get(f"/api/projects/{pid}/export.md").text
    assert md.splitlines()[0] == "# [EN] Livro" and "Mirela's text." in md
    d = c.get(f"/api/projects/{pid}/export.docx")
    assert d.status_code == 200 and d.content[:2] == b"PK"
    assert any(x["id"] == pid for x in c.get("/api/projects").json()["projects"])


def test_argos_glossary_and_protection():
    from wiser.providers import ArgosProvider
    a = ArgosProvider()
    if not a.available("pt", "en")[0]:
        pytest.skip("par pt-en do Argos não instalado")
    out = a.translate_chunk([{"id": "b1", "type": "paragraph", "text": "Aleph (א) pertence ao Livro Verde, ver https://x.org/a."}],
                            {"src": "pt", "tgt": "en", "glossary": [{"source": "Livro Verde", "keep": True}]})
    t = out[0]["text"]
    assert "(א)" in t and "Livro Verde" in t and "https://x.org/a" in t


def test_sanity_flags():
    from wiser.providers import sanity_flags
    assert sanity_flags("5. As sete letras-duplas", "Beth, Gimel and Tav are the seven doubles.")
    assert sanity_flags("Observação: o livro apresenta dez capítulos.", "The book presents ten chapters.")
    assert not sanity_flags("1. Mirela - Rosa.", "1. Mirela - Rose.")
