"""Camada de serviço de IA (somente no servidor).

Provedores:
- "argos": tradução neural local e gratuita (Argos Translate / OpenNMT), offline
  depois de instalado o pacote de idiomas. Não aplica estilo/tom: isso é sinalizado.
- "openai": qualquer API compatível com OpenAI Chat Completions (inclui servidores
  locais como Ollama/llama.cpp). Configurada por variáveis de ambiente:
  WISER_LLM_BASE_URL, WISER_LLM_MODEL, WISER_LLM_API_KEY (opcional p/ servidor local).
Seleção: WISER_PROVIDER = auto | argos | openai | none (padrão auto).
Chaves nunca são enviadas ao navegador.
"""
from __future__ import annotations
import json, os, re, urllib.error, urllib.request

LANG_CODES = {"português": "pt", "portugues": "pt", "inglês": "en", "ingles": "en", "english": "en",
              "espanhol": "es", "francês": "fr", "frances": "fr", "alemão": "de", "alemao": "de",
              "italiano": "it", "russo": "ru", "japonês": "ja", "chinês": "zh", "árabe": "ar",
              "hebraico": "he", "holandês": "nl", "polonês": "pl", "turco": "tr", "coreano": "ko",
              "hindi": "hi", "ucraniano": "uk", "sueco": "sv", "catalão": "ca", "grego": "el"}
PROTECT = re.compile(r"https?://\S+|[\u0590-\u05ff\u0600-\u06ff]+")


def lang_code(name: str) -> str | None:
    n = (name or "").strip().lower()
    n = re.sub(r"\s*\(.*\)$", "", n)
    return LANG_CODES.get(n) or (n if re.fullmatch(r"[a-z]{2}", n) else None)


class ProviderUnavailable(RuntimeError):
    pass


SETUP_HELP = {
    "titulo": "Nenhum provedor de IA está configurado",
    "passos": [
        "Escolha o provedor no arquivo .env do servidor: WISER_PROVIDER=ollama, gemini ou argos (veja .env.example) e reinicie o WISER.",
        "Ollama (local, gratuito): instale o Ollama, rode `ollama serve` e `ollama pull qwen2.5:1.5b` (ou defina WISER_MODEL).",
        "Gemini (nuvem): defina GEMINI_API_KEY (e, se quiser, WISER_MODEL). Na faixa gratuita o Google pode usar o conteúdo enviado.",
        "Argos (local, gratuito, só tradução direta): `.venv/bin/python -m wiser.setup_argos pt en`.",
        "As chaves ficam só no servidor (variáveis de ambiente) e nunca aparecem no navegador.",
    ],
}


class Provider:
    name = "base"
    applies_style = False

    def available(self, src, tgt) -> tuple[bool, str]:
        raise NotImplementedError

    def translate_chunk(self, blocks, ctx) -> list[dict]:
        """blocks: [{id,type,text}] -> [{id,text,flags:[...]}] na MESMA ordem."""
        raise NotImplementedError


class ArgosProvider(Provider):
    name = "argos"
    label = "Argos Translate (local, gratuito)"
    privacy = "Roda neste computador: o manuscrito não sai da máquina. Tradução direta, sem aplicar estilo."

    def _pair(self, src, tgt):
        try:
            import argostranslate.translate as t
        except ImportError:
            return None
        langs = {l.code: l for l in t.get_installed_languages()}
        a, b = langs.get(src), langs.get(tgt)
        if not a or not b:
            return None
        tr = a.get_translation(b)
        return tr

    def available(self, src, tgt):
        if not src or not tgt:
            return False, "Idioma sem código reconhecido pelo tradutor local."
        try:
            import argostranslate  # noqa
        except ImportError:
            return False, "Argos Translate não está instalado."
        if self._pair(src, tgt) is None:
            return False, f"Par de idiomas {src}→{tgt} não instalado no tradutor local."
        return True, ""

    def translate_chunk(self, blocks, ctx):
        tr = self._pair(ctx["src"], ctx["tgt"])
        if tr is None:
            raise ProviderUnavailable("Par de idiomas não instalado.")
        gl = [g for g in ctx.get("glossary", []) if g.get("source")]
        gl.sort(key=lambda g: -len(g["source"]))
        out = []
        rep = {g["source"]: (g["source"] if g.get("keep") or not g.get("target") else g["target"]) for g in gl}
        alts = [PROTECT.pattern] + [r"(?<!\w)" + re.escape(g["source"]) + r"(?!\w)" for g in gl]
        split = re.compile(r"(\(?\s*(?:" + "|".join(alts) + r")\s*\)?)")
        for b in blocks:
            text, flags = b["text"], []
            used = [g for g in rep if re.search(r"(?<!\w)" + re.escape(g) + r"(?!\w)", text)]
            def fix(span):
                for g, t in rep.items():
                    span = re.sub(r"(?<!\w)" + re.escape(g) + r"(?!\w)", t, span)
                return span
            # trechos protegidos (URLs, escrita hebraica/árabe, termos do glossário) não passam pelo tradutor
            pieces = split.split(text)
            res = "".join(fix(pc) if i % 2 else pc if not re.search(r"[^\W\d_]{2}", pc) else
                          (pc[:len(pc) - len(pc.lstrip())] + tr.translate(pc.strip()) + pc[len(pc.rstrip()):])
                          for i, pc in enumerate(pieces))
            if used:
                flags.append({"kind": "glossario_ok", "msg": "Glossário aplicado: " + ", ".join(used)})
            if re.search(r"[“”\"']", b["text"]):
                flags.append({"kind": "citacao", "msg": "Há aspas/termos entre aspas: confira se a citação ou o termo destacado foi tratado como o projeto pede."})
            if b["type"] == "reference":
                res = b["text"] if ctx.get("keep_references", True) else res
                flags.append({"kind": "referencia", "msg": "Referência bibliográfica mantida como no original." if ctx.get("keep_references", True) else "Referência traduzida: confira."})
            out.append({"id": b["id"], "text": res, "flags": sanity_flags(b["text"], res) + flags})
        return out


def sanity_flags(src: str, out: str) -> list[dict]:
    """Checagens automáticas de fidelidade (não substituem revisão humana)."""
    f = []
    ns, no = re.match(r"^\s*(\d+)[.)]", src), re.match(r"^\s*(\d+)[.)]", out)
    if (ns and not no) or (ns and no and ns.group(1) != no.group(1)):
        f.append({"kind": "conferir", "msg": "A numeração do original não foi mantida neste trecho."})
    r = len(out) / max(len(src), 1)
    if len(src) > 25 and (r < 0.6 or r > 1.7):
        f.append({"kind": "conferir", "msg": f"Tamanho muito diferente do original ({r:.0%}): possível omissão ou acréscimo."})
    if src.count(":") > out.count(":"):
        f.append({"kind": "conferir", "msg": "Rótulos com dois-pontos do original (ex.: “Observação:”) podem ter sido omitidos."})
    return f


class ProviderError(RuntimeError):
    """Erro com mensagem clara para o usuário (kind: chave|indisponivel|limite|geracao)."""
    def __init__(self, kind, msg):
        super().__init__(msg); self.kind = kind


def _http_json(url, body, headers, timeout=300):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raw = e.read()[:2000].decode("utf-8", "replace")
        try:
            detail = json.loads(raw).get("error", {}).get("message", raw)
        except (ValueError, AttributeError):
            detail = raw
        detail = detail[:300]
        low = detail.lower()
        if "free tier is not available" in low or "billing" in low:
            raise ProviderError("chave", "A chave é válida, mas a faixa gratuita da API não está disponível para este projeto Google; "
                                         "seria preciso ativar cobrança (o WISER não faz isso). Use outro provedor ou outro projeto. Detalhe: " + detail)
        if e.code == 404 and ("no longer available" in low or "not found" in low):
            raise ProviderError("modelo", "O modelo configurado em WISER_MODEL não está disponível para esta chave. Detalhe: " + detail)
        if e.code == 429:
            raise ProviderError("limite", "Limite de uso do provedor atingido (429). Espere alguns minutos e clique em continuar; o que já foi feito está salvo.")
        if e.code in (401, 403):
            raise ProviderError("chave", f"O provedor recusou a chave de acesso ({e.code}). Confira a variável de ambiente no servidor. Detalhe: {detail}")
        raise ProviderError("geracao", f"O provedor respondeu com erro {e.code}: {detail}")
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise ProviderError("indisponivel", f"Serviço de IA indisponível: {getattr(e, 'reason', e)}")


STYLES = {"fiel": "Faithful to the original: follow sentence form and order closely.",
          "natural": "Natural in the target language: keep meaning and authorial voice, with native fluency.",
          "local": "Adapted to the local audience: adapt cultural references/units ONLY when needed, and flag every such adaptation."}
SYSTEM = ("You adapt manuscripts into another language for an editorial team. Rules: translate every block completely; "
          "do NOT add facts, sources, quotations or interpretations; keep proper names, bibliographic references, numbers, "
          "list numbering and any token like ZQX0 exactly as given; obey the glossary. When an expression has no direct "
          "equivalent or a passage is ambiguous, choose a rendering AND describe the choice in that block's flags (in Portuguese). "
          "Reply ONLY with JSON: {\"items\":[{\"id\":\"...\",\"text\":\"...\",\"flags\":[\"...\"]}]} with the same ids, same order.")


class LLMProvider(Provider):
    applies_style = True

    def _user(self, blocks, ctx):
        return json.dumps({"from": ctx["src_name"], "to": ctx["tgt_name"], "style": STYLES.get(ctx.get("style"), STYLES["natural"]),
                           "audience": ctx.get("audience") or None, "region": ctx.get("region") or None, "tone": ctx.get("tone") or None,
                           "glossary": [{"term": g["source"], "render_as": g["source"] if g.get("keep") or not g.get("target") else g["target"]}
                                        for g in ctx.get("glossary", [])],
                           "blocks": [{"id": b["id"], "type": b["type"], "text": b["text"]} for b in blocks]}, ensure_ascii=False)

    def _complete(self, system, user) -> str:
        raise NotImplementedError

    def translate_chunk(self, blocks, ctx):
        prot, work = [], []
        for b in blocks:
            toks = {}
            def tok(m):
                k = f"ZQX{len(toks)}"; toks[k] = m.group(0); return k
            work.append({**b, "text": PROTECT.sub(tok, b["text"])}); prot.append(toks)
        last = None
        for _ in range(2):  # uma nova tentativa se o JSON vier incompleto
            content = self._complete(SYSTEM, self._user(work, ctx))
            m = re.search(r"\{.*\}", content, re.S)
            try:
                items = json.loads(m.group(0))["items"] if m else []
                byid = {str(i["id"]): i for i in items if isinstance(i, dict) and "id" in i}
            except (ValueError, KeyError, TypeError):
                byid = {}
            if all(b["id"] in byid and str(byid[b["id"]].get("text", "")).strip() for b in blocks):
                break
            last = [b["id"] for b in blocks if b["id"] not in byid]
        else:
            if len(blocks) > 1:  # reparte: pede os trechos que faltaram um a um, mantendo a ordem
                got = {}
                for b in blocks:
                    if b["id"] not in byid or not str(byid[b["id"]].get("text", "")).strip():
                        got[b["id"]] = self.translate_chunk([b], ctx)[0]
                part = {b["id"]: b for b in blocks if b["id"] not in got}
                first = self.translate_chunk_from(byid, [b for b in blocks if b["id"] in part], ctx) if part else []
                firstd = {r["id"]: r for r in first}
                return [got.get(b["id"]) or firstd[b["id"]] for b in blocks]
            raise ProviderError("geracao", f"O modelo não devolveu todos os trechos ({', '.join(last or [])}). Nada foi salvo para esta parte")
        return self.translate_chunk_from(byid, blocks, ctx)

    def translate_chunk_from(self, byid, blocks, ctx):
        out = []
        for b in blocks:
            toks = {}
            def tok(m):
                k = f"ZQX{len(toks)}"; toks[k] = m.group(0); return k
            PROTECT.sub(tok, b["text"])
            i = byid[b["id"]]; text = str(i["text"]); flags = []
            if b["type"] == "reference" and ctx.get("keep_references", True):
                toks = {}  # a referência é mantida igual ao original: nada se perde
            for k, v in toks.items():
                if k in text: text = text.replace(k, v)
                else: flags.append({"kind": "perda", "msg": f"Trecho protegido ausente na adaptação: “{v}”. Confira."})
            for g in ctx.get("glossary", []):
                want = g["source"] if g.get("keep") or not g.get("target") else g["target"]
                if re.search(r"(?<!\w)" + re.escape(g["source"]) + r"(?!\w)", b["text"]) and want not in text:
                    flags.append({"kind": "glossario", "msg": f"Termo do glossário “{g['source']}” deveria aparecer como “{want}”."})
            if b["type"] == "reference" and ctx.get("keep_references", True):
                text = b["text"]; flags.append({"kind": "referencia", "msg": "Referência bibliográfica mantida como no original."})
            flags += [{"kind": "decisao", "msg": str(f)} for f in (i.get("flags") or []) if str(f).strip().lower() not in ("", "none", "null", "n/a", "nenhum", "nenhuma") and len(str(f).split()) >= 3]  # descarta rótulos vazios como "translation_required"
            flags = sanity_flags(b["text"], text) + flags
            out.append({"id": b["id"], "text": text, "flags": flags})
        return out


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self):
        self.base = os.environ.get("WISER_OLLAMA_URL", "http://localhost:11434/v1").rstrip("/")
        self.model = os.environ.get("WISER_MODEL", "qwen2.5:1.5b")
        self.label = f"Ollama local ({self.model})"
        self.privacy = "Roda neste computador: o manuscrito não sai da máquina."

    def available(self, src, tgt):
        try:
            with urllib.request.urlopen(self.base + "/models", timeout=3) as r:
                ids = [m["id"] for m in json.load(r).get("data", [])]
        except Exception:
            return False, f"Ollama não está acessível em {self.base}. Inicie com `ollama serve`."
        if self.model not in ids:
            return False, f"Modelo {self.model} não está instalado no Ollama (`ollama pull {self.model}`)."
        return True, ""

    def _complete(self, system, user):
        r = _http_json(self.base + "/chat/completions", {"model": self.model, "temperature": 0.2, "max_tokens": 3000,
                       "response_format": {"type": "json_object"},
                       "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}, {})
        return r["choices"][0]["message"]["content"]


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self):
        self.key = os.environ.get("GEMINI_API_KEY", "")
        self.model = os.environ.get("WISER_MODEL", "gemini-flash-latest")
        self.label = f"Google Gemini ({self.model})"
        self.privacy = ("O manuscrito é enviado à API do Google Gemini. Na faixa gratuita, o Google pode usar o conteúdo "
                        "enviado para melhorar seus produtos; use uma conta paga se o texto for confidencial.")

    def available(self, src, tgt):
        if not self.key:
            return False, "Chave ausente: defina GEMINI_API_KEY no servidor (arquivo .env)."
        return True, ""

    def _complete(self, system, user):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        r = _http_json(url, {"systemInstruction": {"parts": [{"text": system}]},
                             "contents": [{"role": "user", "parts": [{"text": user}]}],
                             "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}},
                       {"x-goog-api-key": self.key})
        try:
            return r["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            raise ProviderError("geracao", "O Gemini não devolveu texto (possível bloqueio de conteúdo).")


PROVIDERS = {"gemini": GeminiProvider, "ollama": OllamaProvider, "argos": ArgosProvider}


def get_provider(src, tgt):
    """Usa SOMENTE o provedor definido em WISER_PROVIDER. Sem troca silenciosa."""
    choice = os.environ.get("WISER_PROVIDER", "").strip().lower()
    if choice not in PROVIDERS:
        return None, {"ok": False, "reasons": [f"WISER_PROVIDER não definido ou inválido ({choice or 'vazio'}). Use gemini, ollama ou argos."], "help": SETUP_HELP}
    p = PROVIDERS[choice]()
    ok, why = p.available(src, tgt)
    if ok:
        return p, {"ok": True, "provider": p.name, "label": p.label, "applies_style": p.applies_style, "privacy": p.privacy}
    return None, {"ok": False, "provider": p.name, "reasons": [f"{p.label}: {why}"], "help": SETUP_HELP}


def chunk(blocks, budget=2500):
    """Divide em partes por tamanho, sem quebrar blocos e mantendo a ordem."""
    parts, cur, n = [], [], 0
    for b in blocks:
        if cur and n + len(b["text"]) > budget:
            parts.append(cur); cur, n = [], 0
        cur.append(b); n += len(b["text"])
    if cur:
        parts.append(cur)
    return parts
