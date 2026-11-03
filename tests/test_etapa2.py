import io, importlib
from pathlib import Path
import pytest

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WISER_DATA", str(tmp_path))
    import wiser.store as st; importlib.reload(st)
    import wiser.app as app; importlib.reload(app)
    from fastapi.testclient import TestClient
    return TestClient(app.app), app, tmp_path


class Echo:
    """Dublê: devolve um texto fixo por id (simula adaptação boa, ruim e residual)."""
    name, label, applies_style, privacy = "dub", "dublê", True, "teste"
    def __init__(self, table): self.table = table
    def available(self, s, t): return True, ""
    def translate_chunk(self, blocks, ctx):
        return [{"id": b["id"], "text": self.table.get(b["text"], b["text"]), "flags": [{"kind": "decisao", "msg": "Aspas: confirmar tratamento."}] if "“" in b["text"] else []} for b in blocks]


def make(c, app, monkeypatch, text, table, name="Teste"):
    monkeypatch.setattr(app, "get_provider", lambda s, t: (Echo(table), {"ok": True, "label": "dub", "applies_style": True}))
    p = c.post("/api/projects", data={"text": text, "name": name}).json()
    c.patch(f"/api/projects/{p['id']}", json={"settings": {"src": "Português", "tgt": "Inglês"}})
    assert c.post(f"/api/projects/{p['id']}/adapt").status_code == 200
    app._jobs[p["id"]].join(5)
    return p["id"]


# --- 1. detecção de resíduo ---
def test_residue_detection():
    from wiser.review import residue
    pt = "O solo deve ser revolvido antes do plantio e a terra fica mais leve para as raízes."
    assert residue(pt, pt, "pt", "en")["kind"] == "residuo"
    assert residue(pt, "The soil should be turned before planting and the earth becomes lighter for the roots.", "pt", "en") is None


def test_residue_ignores_names_urls_quotes_hebrew_code_refs():
    from wiser.review import residue
    out = "Mirela and Tobias appear in “uma citação que fica em português para o leitor” (א), see https://exemplo.org/da-terra and `para_cada item`."
    assert residue("x", out, "pt", "en") is None
    ref = "Silva, A. Manual da horta. Editora Exemplo, 2020."
    assert residue(ref, ref, "pt", "en", "reference") is None


def test_inconclusive_is_review_needed():
    from wiser.review import residue
    r = residue("Regador", "Regador", "pt", "en")
    assert r is None or r["kind"] == "revisao"
    assert residue("Olá", "Cześć xyz qwe rty uio", "pt", "xx")["kind"] == "revisao"


def test_severity_classes():
    from wiser.review import severity
    assert severity({"kind": "glossario_ok"}) == "info"
    assert severity({"kind": "decisao"}) == "aviso"
    assert severity({"kind": "residuo"}) == "bloqueador"
    assert severity({"kind": "perda"}) == "bloqueador"


# --- 2. exportação ---
PT = "O solo deve ser revolvido antes do plantio e a terra fica mais leve para as raízes."


def test_export_blocked_by_blocker_until_resolved(client, monkeypatch):
    c, app, _ = client
    pid = make(c, app, monkeypatch, "Primeiro parágrafo curto.\n\n" + PT, {"Primeiro parágrafo curto.": "First short paragraph."})
    iss = c.get(f"/api/projects/{pid}/issues").json()
    assert iss["blockers"] and iss["approved"] is False
    assert c.get(f"/api/projects/{pid}/export.md?confirm=true").status_code == 409
    b = iss["blockers"][0]
    # bloqueador não se resolve sem decisão registrada
    assert c.post(f"/api/projects/{pid}/blocks/{b['block']}/flags/{b['n']}/resolve", json={}).status_code == 400
    # corrigir o texto remove o bloqueador
    c.put(f"/api/projects/{pid}/blocks/{b['block']}", json={"text": "The soil should be turned before planting and the earth becomes lighter for the roots."})
    assert not c.get(f"/api/projects/{pid}/issues").json()["blockers"]
    assert c.get(f"/api/projects/{pid}/export.md").status_code == 200


def test_blocker_resolved_by_decision(client, monkeypatch):
    c, app, _ = client
    pid = make(c, app, monkeypatch, PT, {})
    b = c.get(f"/api/projects/{pid}/issues").json()["blockers"][0]
    r = c.post(f"/api/projects/{pid}/blocks/{b['block']}/flags/{b['n']}/resolve", json={"decision": "Mantido em português de propósito."})
    assert r.status_code == 200 and not c.get(f"/api/projects/{pid}/issues").json()["blockers"]


def test_warning_requires_confirmation(client, monkeypatch):
    c, app, _ = client
    pid = make(c, app, monkeypatch, "Ela disse “oi”.", {"Ela disse “oi”.": "She said “hi”."})
    iss = c.get(f"/api/projects/{pid}/issues").json()
    assert iss["warnings"] and not iss["blockers"]
    r = c.get(f"/api/projects/{pid}/export.md")
    assert r.status_code == 409 and "Confirme" in r.json()["detail"]
    assert c.get(f"/api/projects/{pid}/export.md?confirm=true").status_code == 200


def test_missing_blocks_still_block(client):
    c, app, _ = client
    p = c.post("/api/projects", data={"text": "Um.\n\nDois."}).json()
    assert c.get(f"/api/projects/{p['id']}/export.docx?confirm=true").status_code == 409


# --- 3. excluir projeto ---
def test_delete_project_removes_everything(client, monkeypatch):
    c, app, tmp = client
    pid = make(c, app, monkeypatch, "Ela disse “oi”.", {"Ela disse “oi”.": "She said “hi”."}, name="Apagar")
    c.get(f"/api/projects/{pid}/export.md?confirm=true")
    up = c.post("/api/projects", files={"file": ("s.txt", b"Texto qualquer.")}).json()
    d = tmp / "projects" / pid
    assert (d / "exports").iterdir()
    assert c.request("DELETE", f"/api/projects/{pid}", json={"confirm_name": "errado"}).status_code == 400
    assert d.exists()
    assert c.request("DELETE", f"/api/projects/{pid}", json={"confirm_name": "Apagar"}).status_code == 200
    assert not d.exists() and c.get(f"/api/projects/{pid}").status_code == 404
    # projeto com original armazenado (somente-leitura) também é removido
    d2 = tmp / "projects" / up["id"]
    assert any(x.name.startswith("original_") for x in d2.iterdir())
    assert c.request("DELETE", f"/api/projects/{up['id']}", json={"confirm_name": up["name"]}).status_code == 200
    assert not d2.exists()


# --- 4. DOCX ---
def test_docx_lists_and_unsupported():
    from wiser.ingest import ingest
    b, w, k = ingest("s.docx", (FIX / "sintetico.docx").read_bytes())
    items = [x["text"] for x in b if x["type"] == "list_item"]
    assert items == ["- farinha", "- água", "- sal", "1. Misture tudo.", "2. Descanse por uma hora.", "3. Asse por trinta minutos."]
    assert any("Tabela 1" in x for x in w) and any("nota(s) de rodapé" in x for x in w)


def test_docx_export_preserves_markers(client, monkeypatch):
    c, app, _ = client
    import docx
    tr = {"Misture tudo.": "Mix everything.", "farinha": "flour"}
    monkeypatch.setattr(app, "get_provider", lambda s, t: (Echo({}), {"ok": True, "label": "dub", "applies_style": True}))
    p = c.post("/api/projects", files={"file": ("s.docx", (FIX / "sintetico.docx").read_bytes())}).json()
    pid = p["id"]
    c.patch(f"/api/projects/{pid}", json={"settings": {"tgt": "Inglês"}})
    # adaptação manual (sem provedor) para cada trecho, simulando a perda do marcador pelo modelo
    for blk in p["blocks"]:
        body = blk["text"].split(" ", 1)[1] if blk["type"] == "list_item" else blk["text"]
        c.put(f"/api/projects/{pid}/blocks/{blk['id']}", json={"text": tr.get(body, body)})
    for blk in p["blocks"]:
        for f in c.get(f"/api/projects/{pid}").json()["adaptation"][blk["id"]]["flags"]:
            pass
    pj = c.get(f"/api/projects/{pid}").json()
    for bid, a in pj["adaptation"].items():
        for n, f in enumerate(a["flags"]):
            c.post(f"/api/projects/{pid}/blocks/{bid}/flags/{n}/resolve", json={"decision": "teste"})
    md = c.get(f"/api/projects/{pid}/export.md?confirm=true").text
    assert "- flour" in md and "1. Mix everything." in md and "3. Asse por trinta minutos." in md
    out = docx.Document(io.BytesIO(c.get(f"/api/projects/{pid}/export.docx?confirm=true").content))
    paras = [(x.style.name, x.text) for x in out.paragraphs]
    assert ("List Bullet", "flour") in paras and ("List Paragraph", "1.\tMix everything.") in paras


# --- 5. portabilidade ---
def test_no_absolute_paths_in_tests():
    for f in Path(__file__).parent.glob("*.py"):
        s = f.read_text("utf-8")
        for bad in ("/cur" + "sor/", "/ho" + "me/", "/work" + "space/"):
            assert bad not in s, (f, bad)


def test_bind_is_local():
    src = (Path(__file__).parent.parent / "wiser" / "app.py").read_text("utf-8")
    assert 'host="127.0.0.1"' in src and "0.0.0.0" not in src


def test_kept_reference_has_no_false_loss():
    from wiser.providers import LLMProvider
    class P(LLMProvider):
        name = label = privacy = "t"
        def _complete(self, system, user):
            import json
            return json.dumps({"items": [{"id": "b1", "text": "Silva, Garden manual.", "flags": []}]})
    out = P().translate_chunk([{"id": "b1", "type": "reference", "text": "Silva, Manual. https://exemplo.org/h"}], {"src_name": "pt", "tgt_name": "en"})
    assert out[0]["text"] == "Silva, Manual. https://exemplo.org/h"
    assert not any(f["kind"] == "perda" for f in out[0]["flags"])
