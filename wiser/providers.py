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
import json, os, re, urllib.request

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
        "Opção gratuita e local (recomendada): no servidor, rode `.venv/bin/python -m wiser.setup_argos pt en` para instalar o par de idiomas (ex.: português → inglês). Depois reinicie o WISER.",
        "Opção com modelo de linguagem (estilos completos): defina no servidor WISER_PROVIDER=openai, WISER_LLM_BASE_URL (ex.: http://127.0.0.1:11434/v1 para Ollama local), WISER_LLM_MODEL e, se o serviço exigir, WISER_LLM_API_KEY.",
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
        for b in blocks:
            text, toks, flags = b["text"], {}, []
            def tok(val):
                k = f"ZQX{len(toks)}"; toks[k] = val; return k
            text = PROTECT.sub(lambda m: tok(m.group(0)), text)
            used = []
            for g in gl:
                pat = re.compile(r"(?<!\w)" + re.escape(g["source"]) + r"(?!\w)")
                if pat.search(text):
                    tgt = g["source"] if g.get("keep") or not g.get("target") else g["target"]
                    text = pat.sub(lambda m: tok(tgt), text); used.append(g["source"])
            res = tr.translate(text) if text.strip() else text
            for k, v in toks.items():
                if k in res:
                    res = res.replace(k, v)
                else:
                    flags.append({"kind": "conferir", "msg": f"Trecho protegido pode ter sido perdido: “{v}”. Confira."})
            if used:
                flags.append({"kind": "glossario", "msg": "Glossário aplicado: " + ", ".join(used)})
            if re.search(r"[“”\"']", b["text"]):
                flags.append({"kind": "citacao", "msg": "Há aspas/termos entre aspas: confira se a citação ou o termo destacado foi tratado como o projeto pede."})
            if b["type"] == "reference":
                res = b["text"] if ctx.get("keep_references", True) else res
                flags.append({"kind": "referencia", "msg": "Referência bibliográfica mantida como no original." if ctx.get("keep_references", True) else "Referência traduzida: confira."})
            out.append({"id": b["id"], "text": res, "flags": flags})
        return out


class OpenAICompatProvider(Provider):
    name = "openai"
    applies_style = True

    def __init__(self):
        self.base = os.environ.get("WISER_LLM_BASE_URL", "").rstrip("/")
        self.model = os.environ.get("WISER_LLM_MODEL", "")
        self.key = os.environ.get("WISER_LLM_API_KEY", "")
        self.label = f"Modelo de linguagem ({self.model or 'não definido'})"

    def available(self, src, tgt):
        if not self.base or not self.model:
            return False, "WISER_LLM_BASE_URL e WISER_LLM_MODEL não definidos."
        return True, ""

    def _prompt(self, blocks, ctx):
        styles = {"fiel": "Fiel ao original: siga de perto a forma e a ordem das frases.",
                  "natural": "Natural no idioma de destino: preserve o sentido e a voz, com fluência nativa.",
                  "local": "Adaptado ao público local: adapte unidades e referências culturais SÓ quando necessário, e sinalize cada adaptação."}
        sys = ("Você adapta manuscritos para outro idioma. Regras: não acrescente fatos, fontes, citações nem interpretações; "
               "preserve nomes próprios, referências bibliográficas, URLs, escrita hebraica/árabe e números; preserve a numeração. "
               "Quando uma expressão não tiver equivalente direto, ou o trecho for ambíguo, proponha uma solução E sinalize em flags. "
               "Responda APENAS JSON: {\"items\":[{\"id\":...,\"text\":...,\"flags\":[\"...\"]}]} com os mesmos ids e ordem.")
        user = {"de": ctx["src_name"], "para": ctx["tgt_name"], "estilo": styles.get(ctx.get("style"), styles["natural"]),
                "publico": ctx.get("audience"), "regiao": ctx.get("region"), "tom": ctx.get("tone"),
                "glossario": ctx.get("glossary", []), "manter_referencias": ctx.get("keep_references", True),
                "blocos": [{"id": b["id"], "tipo": b["type"], "texto": b["text"]} for b in blocks]}
        return sys, json.dumps(user, ensure_ascii=False)

    def translate_chunk(self, blocks, ctx):
        sys, user = self._prompt(blocks, ctx)
        body = json.dumps({"model": self.model, "temperature": 0.2,
                           "messages": [{"role": "system", "content": sys}, {"role": "user", "content": user}]}).encode()
        req = urllib.request.Request(self.base + "/chat/completions", data=body, headers={
            "Content-Type": "application/json", **({"Authorization": "Bearer " + self.key} if self.key else {})})
        with urllib.request.urlopen(req, timeout=300) as r:
            content = json.load(r)["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", content, re.S)
        items = json.loads(m.group(0))["items"] if m else []
        byid = {i["id"]: i for i in items}
        out = []
        for b in blocks:
            i = byid.get(b["id"])
            if not i:
                raise ProviderUnavailable(f"O modelo não devolveu o bloco {b['id']}; nada foi salvo para este trecho.")
            out.append({"id": b["id"], "text": i["text"],
                        "flags": [{"kind": "decisao", "msg": f} for f in i.get("flags", [])]})
        return out


def get_provider(src, tgt):
    """Retorna (provider|None, status dict)."""
    choice = os.environ.get("WISER_PROVIDER", "auto").lower()
    cands = {"argos": [ArgosProvider()], "openai": [OpenAICompatProvider()], "none": [],
             "auto": [OpenAICompatProvider(), ArgosProvider()]}.get(choice, [])
    reasons = []
    for p in cands:
        ok, why = p.available(src, tgt)
        if ok:
            return p, {"ok": True, "provider": p.name, "label": p.label, "applies_style": p.applies_style}
        reasons.append(f"{p.name}: {why}")
    return None, {"ok": False, "reasons": reasons, "help": SETUP_HELP}


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
