"""Revisão automática: resíduo do idioma de origem e classificação de sinalizações.

Severidades:
- info: informativo (ex.: glossário aplicado). Não exige ação.
- aviso: exige decisão editorial; exportar com aviso aberto pede confirmação explícita.
- bloqueador: impede exportar até ser resolvido (editar o trecho ou registrar decisão).
Nada é aprovado automaticamente: a ausência de sinalização não significa "aprovado".
"""
from __future__ import annotations
import re

SEVERITY = {"glossario_ok": "info", "referencia": "info", "glossario": "aviso", "citacao": "aviso",
            "conferir": "aviso", "decisao": "aviso", "revisao": "aviso", "residuo": "bloqueador", "perda": "bloqueador"}

STOP = {
    "pt": "o a os as um uma de do da dos das em no na nos nas por para com não que se é são foi ser está mas ou como mais também pelo pela pelos pelas ao aos à às seu sua seus suas este esta esse essa isso isto já ainda entre sem sobre quando muito onde depois cada outro outra".split(),
    "en": "the a an of and to in is are was be it that this with for on as by not or but from which at their its into also each other when there".split(),
    "es": "el la los las un una de del en y que es son por para con no se su sus como más pero o al lo este esta también entre sin sobre".split(),
    "fr": "le la les un une des de du et en est sont que qui pour avec ne pas se sur dans au aux ce cette mais ou plus comme aussi entre sans".split(),
    "de": "der die das ein eine und ist sind nicht mit von zu den dem des im auf für als auch oder aber wie sich bei nach aus über".split(),
    "it": "il lo la i gli le un una di del della e è sono che per con non si in al nel come più ma anche tra senza".split(),
    "pl": "i w na z do się nie jest są to że jak o od po za przez dla oraz ale lub a ten ta te tego jego jej ich także między bez".split(),
}
# palavras iguais em vários idiomas não contam como evidência
AMBIG = {"a", "o", "e", "de", "la", "le", "in", "no", "se", "i", "do", "a", "as", "con", "per", "en", "to", "on", "die"}

STRIP = [re.compile(p) for p in (r"https?://\S+", r"`[^`]*`", r"[\u0590-\u05ff\u0600-\u06ff]+", r"“[^”]*”", r'"[^"]*"',
                                     r"(?<![\w])'[^']{1,80}'(?![\w])", r"\b\d[\d.,:;-]*\b")]


def _words(text):
    for rx in STRIP:
        text = rx.sub(" ", text)
    out = []
    for i, w in enumerate(re.findall(r"[^\W\d_]+(?:['’-][^\W\d_]+)*", text)):
        if w[:1].isupper() and not w.isupper():
            continue  # nomes próprios (e inícios de frase): ignorados de propósito
        out.append(w.lower())
    return out


def residue(src_text, out_text, src, tgt, btype="paragraph", kept=False):
    """Retorna None (sem evidência de resíduo) ou uma sinalização."""
    if kept or btype in ("reference",) or src == tgt:
        return None
    S, T = set(STOP.get(src, [])) - AMBIG, set(STOP.get(tgt, [])) - AMBIG
    words = _words(out_text)
    if not S or not T:
        return {"kind": "revisao", "msg": "Revisão necessária: não há verificação automática de idioma para este par."}
    if len(words) < 4:
        if words and out_text.strip() == src_text.strip():
            return {"kind": "revisao", "msg": "Revisão necessária: o trecho ficou idêntico ao original e é curto demais para verificar o idioma."}
        return None
    s = sum(w in S for w in words); t = sum(w in T for w in words)
    if s >= 2 and s > t:
        return {"kind": "residuo", "msg": f"Trecho parece continuar no idioma de origem ({s} palavras típicas da origem, {t} do destino)."}
    if s >= 2 and s * 2 >= t:
        return {"kind": "revisao", "msg": "Revisão necessária: mistura de palavras do idioma de origem e do destino."}
    if t == 0 and len(words) >= 8:
        return {"kind": "revisao", "msg": "Revisão necessária: não foi possível confirmar o idioma de destino neste trecho."}
    return None


def severity(flag):
    return SEVERITY.get(flag.get("kind"), "aviso")


def recheck(block, adaptation, src, tgt):
    """Reaplica a checagem de resíduo; mantém as demais sinalizações."""
    flags = [f for f in adaptation.get("flags", []) if f.get("kind") not in ("residuo", "revisao") or f.get("resolved")]
    kept = block["type"] == "quote" and adaptation.get("text", "").strip() == block["text"].strip() and adaptation.get("keep_quote")
    r = residue(block["text"], adaptation.get("text", ""), src, tgt, block["type"], kept)
    if r and not any(f.get("kind") == r["kind"] and f.get("msg") == r["msg"] and f.get("resolved") for f in flags):
        flags.insert(0, r)
    for f in flags:
        f["severity"] = severity(f)
    adaptation["flags"] = flags
    return adaptation


def issues(p, lang_code):
    """Pendências para exportação."""
    missing = [b["id"] for b in p["blocks"] if b["id"] not in p["adaptation"]]
    byid = {b["id"]: b for b in p["blocks"]}
    blockers, warnings, infos = [], [], []
    for bid, a in p["adaptation"].items():
        for n, f in enumerate(a.get("flags", [])):
            if f.get("resolved"):
                continue
            item = {"block": bid, "n": n, "msg": f["msg"], "kind": f.get("kind"), "excerpt": byid.get(bid, {}).get("text", "")[:90]}
            {"bloqueador": blockers, "aviso": warnings, "info": infos}[severity(f)].append(item)
    order = {b["id"]: i for i, b in enumerate(p["blocks"])}
    for l in (blockers, warnings, infos):
        l.sort(key=lambda x: (order.get(x["block"], 0), x["n"]))
    return {"missing": missing, "blockers": blockers, "warnings": warnings, "infos": infos,
            "approved": False, "note": "Sem aprovação automática: a revisão final é editorial."}
