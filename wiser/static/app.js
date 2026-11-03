"use strict";
const $ = (s, el = document) => el.querySelector(s);
const main = $("#main");
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const TYPES = {heading:"Título",paragraph:"Parágrafo",list_item:"Item de lista",quote:"Citação",note:"Nota",reference:"Referência"};
const SEVL = {info: "Informativo", aviso: "Decisão editorial", bloqueador: "Bloqueador"};
const sev = f => f.severity || ({glossario_ok: "info", referencia: "info", residuo: "bloqueador", perda: "bloqueador"})[f.kind] || "aviso";
const STYLES = [["fiel","Fiel ao original","Segue de perto as frases e a forma do texto."],
  ["natural","Natural no idioma de destino","Mantém sentido e voz, com leitura fluente. (Recomendado)"],
  ["local","Adaptado ao público local","Ajusta referências culturais quando necessário, sempre sinalizando."]];
let P = null, LANGS = [], ACCEPTED = [], curSec = 0, poll = null;

async function api(path, opt = {}) {
  const r = await fetch(path, opt);
  const ct = r.headers.get("content-type") || "";
  const body = ct.includes("json") ? await r.json() : null;
  if (!r.ok) { const e = new Error((body && (typeof body.detail === "string" ? body.detail : "Erro")) || r.statusText); e.body = body; e.status = r.status; throw e; }
  return body;
}
const json = (m, b) => ({method: m, headers: {"Content-Type": "application/json"}, body: JSON.stringify(b)});
function toast(m) { const t = $("#toast"); t.textContent = m; t.style.display = "block"; clearTimeout(t._h); t._h = setTimeout(() => t.style.display = "none", 2600); }
function go(h) { location.hash = h; }
function focusMain() { const h = $("h1", main); (h || main).setAttribute("tabindex", "-1"); (h || main).focus(); }

function setSteps(n) {
  const nav = $("#steps"); nav.hidden = !n;
  nav.querySelectorAll("li").forEach(li => {
    const s = +li.dataset.step;
    li.toggleAttribute("aria-current", s === n); if (s === n) li.setAttribute("aria-current", "step");
    li.classList.toggle("done", s < n);
  });
}

async function route() {
  clearInterval(poll);
  if (!LANGS.length) { const l = await api("/api/languages"); LANGS = l.languages; ACCEPTED = l.accepted; }
  const m = location.hash.match(/^#\/p\/([a-f0-9]{12})\/(\d)/);
  if (location.hash === "#/novo") return step1();
  if (!m) return home();
  P = await api("/api/projects/" + m[1]);
  const s = +m[2];
  if (P.step !== s) api("/api/projects/" + P.id, json("PATCH", {step: s}));
  ({1: step1view, 2: step2, 3: step3, 4: step4, 5: step5})[s]();
}
window.addEventListener("hashchange", route);

async function home() {
  setSteps(0);
  const {projects} = await api("/api/projects");
  main.innerHTML = `<h1>Adapte seu manuscrito para outro idioma</h1>
  <p class="lead">Envie ou cole o texto, escolha o idioma e o estilo, revise lado a lado e exporte em Word ou Markdown. O arquivo original nunca é alterado.</p>
  <p><button class="primary big" id="new">Criar adaptação</button></p>
  <section class="card" aria-labelledby="h-proj"><h2 id="h-proj">Projetos salvos</h2>
  ${projects.length ? `<ul class="list">${projects.map(p => `<li><span><b>${esc(p.name)}</b><br><small>${esc(p.tgt || "idioma não definido")} · ${p.progress} trechos adaptados · ${new Date(p.updated*1000).toLocaleString("pt-BR")}</small></span>
    <span class="act"><a class="btn" href="#/p/${p.id}/${p.step || 2}">Retomar</a> <button type="button" class="danger" data-del="${p.id}" data-name="${esc(p.name)}">Excluir</button></span></li>`).join("")}</ul>` : `<p>Nenhum projeto ainda.</p>`}</section>`;
  $("#new").onclick = () => go("#/novo");
  main.querySelectorAll("[data-del]").forEach(b => b.onclick = () => askDelete(b.dataset.del, b.dataset.name));
  focusMain();
}

function askDelete(id, name) {
  const dlg = document.createElement("dialog");
  dlg.setAttribute("aria-labelledby", "dlg-t");
  dlg.innerHTML = `<form method="dialog"><h2 id="dlg-t">Excluir “${esc(name)}”?</h2>
   <p>Isso apaga <b>definitivamente</b> deste computador: o projeto, a cópia do manuscrito enviada, a adaptação, o glossário e as exportações salvas. Não dá para desfazer.</p>
   <label for="dlg-n">Para confirmar, digite o nome do projeto: <b>${esc(name)}</b></label><input type="text" id="dlg-n" autocomplete="off">
   <p id="dlg-m" aria-live="polite"></p>
   <div class="actions"><button value="cancel">Cancelar</button><button type="button" class="danger" id="dlg-ok">Excluir definitivamente</button></div></form>`;
  document.body.append(dlg); dlg.showModal(); $("#dlg-n", dlg).focus();
  dlg.addEventListener("close", () => dlg.remove());
  $("#dlg-ok", dlg).onclick = async () => {
    try { await api("/api/projects/" + id, json("DELETE", {confirm_name: $("#dlg-n", dlg).value})); dlg.close(); toast("Projeto excluído"); home(); }
    catch (e) { $("#dlg-m", dlg).innerHTML = `<span class="err">${esc(e.message)}</span>`; }
  };
}

function step1() {
  setSteps(1);
  main.innerHTML = `<h1>1. Carregar o manuscrito</h1>
  <p>Formatos aceitos: <b>${ACCEPTED.join(", ")}</b>, ou cole o texto. Limite de 20 MB.</p>
  <form id="f" class="card">
    <label for="name">Nome do projeto <span class="hint">(opcional)</span></label><input type="text" id="name" name="name">
    <label for="file">Arquivo do manuscrito</label><input type="file" id="file" name="file" accept=".docx,.pdf,.md,.markdown,.txt">
    <p class="hint">ou</p>
    <label for="text">Colar texto</label><textarea id="text" name="text" placeholder="Cole aqui o seu manuscrito…"></textarea>
    <div id="msg" aria-live="polite"></div>
    <div class="actions"><a class="btn" href="#/">Voltar</a><button class="primary" type="submit">Continuar</button></div>
  </form>`;
  $("#f").onsubmit = async e => {
    e.preventDefault();
    const fd = new FormData();
    const f = $("#file").files[0], t = $("#text").value;
    if (!f && !t.trim()) { $("#msg").innerHTML = `<p class="err">Escolha um arquivo ou cole um texto.</p>`; return; }
    fd.append("name", $("#name").value); if (f) fd.append("file", f); else fd.append("text", t);
    $("#msg").innerHTML = "<p>Lendo o manuscrito…</p>";
    try { const p = await api("/api/projects", {method: "POST", body: fd}); go(`#/p/${p.id}/1`); }
    catch (err) { $("#msg").innerHTML = `<p class="err">${esc(err.message)}</p>`; }
  };
  focusMain();
}

function counts(p) { const c = {}; p.blocks.forEach(b => c[b.type] = (c[b.type] || 0) + 1); return Object.entries(c).map(([k, v]) => `${v} ${TYPES[k].toLowerCase()}${v > 1 ? "(s)" : ""}`).join(" · "); }

function step1view() {
  setSteps(1);
  main.innerHTML = `<h1>1. Manuscrito carregado</h1>
  <p><b>${esc(P.name)}</b> — ${esc(P.source_kind)}. Encontramos ${P.blocks.length} trechos: ${counts(P)}. Seções: ${P.sections.length}.</p>
  ${P.warnings.filter(w => !w.startsWith("Não importado")).map(w => `<p class="warn">⚠ ${esc(w)}</p>`).join("")}
  ${P.warnings.some(w => w.startsWith("Não importado")) ? `<div class="warn"><b>Detectado no arquivo e NÃO importado</b> (não aparecerá na adaptação nem na exportação):<ul>${P.warnings.filter(w => w.startsWith("Não importado")).map(w => `<li>${esc(w.replace(/^Não importado: /, ""))}</li>`).join("")}</ul></div>` : ""}
  <details class="card"><summary>Ver a estrutura detectada</summary><ol>${P.blocks.map(b => `<li><span class="kind">${TYPES[b.type]}</span> ${esc(b.text.slice(0, 120))}</li>`).join("")}</ol></details>
  <div class="actions"><a class="btn" href="#/">Início</a><a class="btn primary" href="#/p/${P.id}/2">Continuar para idiomas</a></div>`;
  focusMain();
}

function langField(id, label, val) {
  return `<label for="${id}">${label} <span class="hint">digite para buscar, ou escreva outro idioma</span></label>
  <input type="search" id="${id}" list="${id}-l" value="${esc(val)}" autocomplete="off"><datalist id="${id}-l">${LANGS.map(l => `<option value="${l}">`).join("")}</datalist>`;
}

async function step2() {
  setSteps(2);
  main.innerHTML = `<h1>2. Idiomas</h1><form id="f" class="card"><div class="row"><div>${langField("src", "Idioma do original", P.settings.src || "Português")}</div><div>${langField("tgt", "Idioma de destino", P.settings.tgt || "")}</div></div>
  <div id="st" aria-live="polite"></div>
  <div class="actions"><a class="btn" href="#/p/${P.id}/1">Voltar</a><button class="primary">Continuar para estilo</button></div></form>`;
  const check = async () => {
    const s = await api(`/api/status?src=${encodeURIComponent($("#src").value)}&tgt=${encodeURIComponent($("#tgt").value)}`);
    $("#st").innerHTML = !$("#tgt").value ? "" : s.ok ? `<p class="okbox">Pronto para adaptar com: ${esc(s.label)}.</p>` : setupHelp(s);
  };
  $("#tgt").onchange = check; $("#src").onchange = check; if (P.settings.tgt) check();
  $("#f").onsubmit = async e => {
    e.preventDefault();
    if (!$("#tgt").value.trim()) { $("#st").innerHTML = `<p class="err">Escolha o idioma de destino.</p>`; $("#tgt").focus(); return; }
    await api("/api/projects/" + P.id, json("PATCH", {settings: {src: $("#src").value.trim(), tgt: $("#tgt").value.trim()}}));
    go(`#/p/${P.id}/3`);
  };
  focusMain();
}

function setupHelp(s) {
  return `<div class="warn"><b>${esc(s.help.titulo)}</b> para este par de idiomas. A adaptação não será feita até isso ser configurado.<ol>${s.help.passos.map(p => `<li>${esc(p)}</li>`).join("")}</ol><small>Detalhes: ${esc(s.reasons.join(" | "))}</small></div>`;
}

async function step3() {
  setSteps(3);
  const s = P.settings;
  main.innerHTML = `<h1>3. Estilo da adaptação</h1><form id="f">
  <fieldset class="card"><legend><b>Como o texto deve soar?</b></legend><div class="choices">${STYLES.map(([v, t, d]) => `<label class="choice"><input type="radio" name="style" value="${v}" ${s.style === v ? "checked" : ""}><b>${t}</b><small>${d}</small></label>`).join("")}</div></fieldset>
  <details class="card" ${s.audience || s.region || s.tone ? "open" : ""}><summary><b>Ajustes opcionais</b> — público, região, tom e termos fixos</summary>
   <div class="row"><div><label for="audience">Para quem é o texto? <span class="hint">opcional</span></label><input type="text" id="audience" value="${esc(s.audience)}" placeholder="ex.: estudantes iniciantes"></div>
   <div><label for="region">Região <span class="hint">opcional</span></label><input type="text" id="region" value="${esc(s.region)}" placeholder="ex.: Estados Unidos"></div>
   <div><label for="tone">Tom de voz <span class="hint">opcional</span></label><input type="text" id="tone" value="${esc(s.tone)}" placeholder="ex.: didático e sereno"></div></div>
   <label><input type="checkbox" id="keepref" ${s.keep_references ? "checked" : ""}> Manter referências bibliográficas como no original</label>
  </details>
  <section class="card" aria-labelledby="h-gl"><h2 id="h-gl">Glossário do projeto</h2><p class="hint">Termos que devem ficar sempre iguais. Deixe "tradução" vazia ou marque "manter" para não traduzir.</p>
   <table class="gl"><thead><tr><th scope="col">Termo no original</th><th scope="col">Tradução fixa</th><th scope="col">Manter</th><th scope="col"><span class="hint">Ação</span></th></tr></thead><tbody id="gl"></tbody></table>
   <div class="actions" style="justify-content:flex-start"><button type="button" id="add">Adicionar termo</button><button type="button" id="sug">Sugerir nomes recorrentes</button></div><div id="sugbox"></div></section>
  <section class="card" aria-labelledby="h-prov"><h2 id="h-prov">Antes de gerar</h2><div id="prov">Verificando o provedor de IA…</div></section>
  <div id="st" aria-live="polite"></div>
  <div class="actions"><a class="btn" href="#/p/${P.id}/2">Voltar</a><button class="primary" id="run">${Object.keys(P.adaptation).length ? "Salvar e continuar adaptação" : "Gerar adaptação"}</button></div></form>`;
  api(`/api/status?src=${encodeURIComponent(s.src)}&tgt=${encodeURIComponent(s.tgt)}`).then(st => {
    $("#prov").innerHTML = st.ok ? `<p>Provedor selecionado: <b>${esc(st.label)}</b>.</p><p class="warn">🔒 ${esc(st.privacy)}</p>${st.applies_style ? "" : `<p class="warn">Este provedor faz tradução direta: estilo, público, região e tom não são aplicados automaticamente.</p>`}` : setupHelp(st);
    $("#run").disabled = !st.ok;
  });
  let gl = P.glossary.slice();
  const draw = () => { $("#gl").innerHTML = gl.map((g, i) => `<tr><td><input type="text" aria-label="Termo ${i+1}" data-i="${i}" data-k="source" value="${esc(g.source)}"></td><td><input type="text" aria-label="Tradução do termo ${i+1}" data-i="${i}" data-k="target" value="${esc(g.target)}"></td><td><input type="checkbox" aria-label="Manter termo ${i+1}" data-i="${i}" data-k="keep" ${g.keep ? "checked" : ""}></td><td><button type="button" data-del="${i}">Remover</button></td></tr>`).join("") || `<tr><td colspan="4">Nenhum termo.</td></tr>`; };
  draw();
  $("#gl").oninput = e => { const i = e.target.dataset.i; if (i == null) return; gl[i][e.target.dataset.k] = e.target.type === "checkbox" ? e.target.checked : e.target.value; };
  $("#gl").onclick = e => { if (e.target.dataset.del != null) { gl.splice(+e.target.dataset.del, 1); draw(); } };
  $("#add").onclick = () => { gl.push({source: "", target: "", keep: false}); draw(); $("#gl tr:last-child input").focus(); };
  $("#sug").onclick = async () => {
    const {suggestions} = await api(`/api/projects/${P.id}/glossary/suggest`);
    $("#sugbox").innerHTML = suggestions.length ? `<p>Clique para adicionar como “manter”:</p>` + suggestions.map(w => `<button type="button" class="sg" style="margin:3px">${esc(w)}</button>`).join("") : "<p>Sem sugestões.</p>";
    $("#sugbox").querySelectorAll(".sg").forEach(b => b.onclick = () => { gl.push({source: b.textContent, target: "", keep: true}); b.remove(); draw(); });
  };
  $("#f").onsubmit = async e => {
    e.preventDefault();
    const settings = {style: $("input[name=style]:checked")?.value || "natural", audience: $("#audience").value, region: $("#region").value, tone: $("#tone").value, keep_references: $("#keepref").checked};
    await api("/api/projects/" + P.id, json("PATCH", {settings}));
    await api(`/api/projects/${P.id}/glossary`, json("PUT", {entries: gl}));
    try { await api(`/api/projects/${P.id}/adapt`, {method: "POST"}); go(`#/p/${P.id}/4`); }
    catch (err) { $("#st").innerHTML = err.body && err.body.status ? setupHelp(err.body.status) : `<p class="err">${esc(err.message)}</p>`; }
  };
  focusMain();
}

function jobBox() {
  const j = P.job || {};
  if (j.state === "running") return `<div class="card"><p>Adaptando com ${esc(j.provider)}… parte ${j.done} de ${j.total}. Você pode sair; o progresso fica salvo.</p><progress max="${j.total}" value="${j.done}"></progress></div>`;
  if (j.state === "blocked") return setupHelp(j.status);
  if (j.state === "error") return `<p class="err"><b>${({chave:"Chave de acesso",indisponivel:"Serviço indisponível",limite:"Limite de uso",geracao:"Erro de geração",modelo:"Modelo indisponível"})[j.kind] || "Erro"}:</b> ${esc(j.message)} <button id="retry">Continuar adaptação</button></p>`;
  if (j.state === "done") return (j.notes || []).map(n => `<p class="warn">⚠ ${esc(n)}</p>`).join("") + `<p class="hint">Gerado por: ${esc(j.provider)}</p>`;
  return "";
}

async function step4() {
  setSteps(4);
  const ad = P.adaptation, flagged = P.blocks.filter(b => (ad[b.id]?.flags || []).some(f => !f.resolved && sev(f) !== "info")).length;
  const done = P.blocks.filter(b => ad[b.id]).length;
  main.innerHTML = `<h1>4. Revisar</h1><p>${done} de ${P.blocks.length} trechos adaptados · <b>${flagged}</b> com pontos para decidir. Edite à direita; tudo é salvo automaticamente. Nenhum trecho é aprovado automaticamente.</p>
  <div id="job">${jobBox()}</div>
  <div class="review"><nav class="toc" aria-label="Seções">${P.sections.map((s, i) => { const n = s.blocks.filter(id => (ad[id]?.flags || []).some(f => !f.resolved && sev(f) !== "info")).length; return `<button data-s="${i}" ${i === curSec ? 'aria-current="true"' : ""}>${esc(s.title.slice(0, 60))}${n ? ` <span class="badge" aria-label="${n} pendentes">${n}</span>` : ""}</button>`; }).join("")}</nav>
  <section id="sec" aria-live="polite"></section></div>
  <div class="actions"><a class="btn" href="#/p/${P.id}/3">Voltar ao estilo</a><a class="btn primary" href="#/p/${P.id}/5">Continuar para exportar</a></div>`;
  $(".toc").onclick = e => { const b = e.target.closest("button"); if (!b) return; curSec = +b.dataset.s; $(".toc").querySelectorAll("button").forEach(x => x.removeAttribute("aria-current")); b.setAttribute("aria-current", "true"); drawSec(); $("#sec h2").focus(); };
  $("#retry")?.addEventListener("click", async () => { await api(`/api/projects/${P.id}/adapt`, {method: "POST"}); route(); });
  if (curSec >= P.sections.length) curSec = 0;
  drawSec();
  if (P.job?.state === "running") poll = setInterval(async () => { P = await api("/api/projects/" + P.id); if (P.job.state !== "running") { clearInterval(poll); step4(); } else $("#job").innerHTML = jobBox(); }, 1500);
  focusMain();
}

function drawSec() {
  const s = P.sections[curSec], byId = Object.fromEntries(P.blocks.map(b => [b.id, b]));
  $("#sec").innerHTML = `<h2 tabindex="-1">${esc(s.title)}</h2><div class="colhead"><span>Original (${esc(P.settings.src)})</span><span>Adaptação (${esc(P.settings.tgt)})</span></div>` +
    s.blocks.map(id => { const b = byId[id], a = P.adaptation[id];
      return `<div class="pair"><div class="orig"><span class="kind">${TYPES[b.type]}</span>\n${esc(b.text)}</div><div>
      ${a ? `<label class="kind" for="t-${id}">Adaptação — ${TYPES[b.type]}${a.edited ? " · editado" : ""}</label><textarea id="t-${id}" data-id="${id}">${esc(a.text)}</textarea>
      ${(a.flags || []).map((f, n) => { const sv = sev(f); return `<div class="flag sev-${sv} ${f.resolved ? "resolved" : ""}"><span><b>${SEVL[sv]}:</b> ${esc(f.msg)}${f.decision ? ` <i>— decisão: ${esc(f.decision)}</i>` : ""}</span>${f.resolved || sv === "info" ? "" : sv === "bloqueador" ? `<span class="dec"><label class="sr" for="d-${id}-${n}">Decisão editorial</label><input type="text" id="d-${id}-${n}" placeholder="Decisão (ex.: manter de propósito)"><button data-r="${id}:${n}">Registrar</button></span>` : `<button data-r="${id}:${n}">Decidido</button>`}</div>`; }).join("")}` : `<p class="hint">Ainda não adaptado.</p>`}</div></div>`; }).join("");
  $("#sec").oninput = e => { const id = e.target.dataset.id; if (!id) return; clearTimeout(e.target._t); e.target._t = setTimeout(async () => { const before = (P.adaptation[id].flags || []).length; P.adaptation[id] = await api(`/api/projects/${P.id}/blocks/${id}`, json("PUT", {text: e.target.value})); toast("Salvo"); if ((P.adaptation[id].flags || []).length !== before) { const pos = e.target.selectionStart; drawSec(); const t = $(`#t-${id}`); t.focus(); t.setSelectionRange(pos, pos); } }, 800); };
  $("#sec").onclick = async e => { const r = e.target.dataset.r; if (!r) return; const [id, n] = r.split(":"); const inp = $(`#d-${id}-${n}`);
    try { await api(`/api/projects/${P.id}/blocks/${id}/flags/${n}/resolve`, json("POST", {decision: inp ? inp.value : ""})); } catch (err) { toast(err.message); inp?.focus(); return; } P.adaptation[id].flags[n].resolved = true; drawSec(); };
}

async function step5() {
  setSteps(5);
  const I = await api(`/api/projects/${P.id}/issues`);
  const li = x => `<li><a href="#/p/${P.id}/4" data-b="${x.block}">${esc(x.excerpt)}…</a> — ${esc(x.msg)}</li>`;
  const blocked = I.missing.length || I.blockers.length;
  main.innerHTML = `<h1>5. Exportar</h1>
  ${I.missing.length ? `<p class="err">Ainda há ${I.missing.length} trecho(s) sem adaptação. Volte à revisão e conclua a adaptação.</p>` : ""}
  ${I.blockers.length ? `<div class="err"><b>${I.blockers.length} bloqueador(es)</b> impedem a exportação até serem resolvidos (corrija o texto ou registre a decisão):<ul>${I.blockers.map(li).join("")}</ul></div>` : ""}
  ${I.warnings.length ? `<div class="warn"><b>${I.warnings.length} aviso(s) sem decisão editorial:</b><ul>${I.warnings.map(li).join("")}</ul></div>` : ""}
  ${!blocked && !I.warnings.length ? `<p class="okbox">Sem pendências automáticas. Lembre: isso não é uma aprovação — a revisão final é sua.</p>` : ""}
  <div class="card"><p>O arquivo exportado contém só a versão adaptada e revisada. O original fica intacto.</p>
  ${!blocked && I.warnings.length ? `<label><input type="checkbox" id="conf"> Revisei os avisos acima e quero exportar mesmo assim.</label>` : ""}
  <div class="actions" style="justify-content:flex-start"><button class="primary" data-f="docx" ${blocked ? "disabled" : ""}>Baixar Word (.docx)</button>
  <button data-f="md" ${blocked ? "disabled" : ""}>Baixar Markdown (.md)</button></div><p id="em" aria-live="polite"></p></div>
  <div class="actions"><a class="btn" href="#/p/${P.id}/4">Voltar à revisão</a><a class="btn" href="#/">Início</a></div>`;
  main.querySelectorAll("[data-b]").forEach(a => a.onclick = () => { curSec = P.sections.findIndex(s => s.blocks.includes(a.dataset.b)); });
  main.querySelectorAll("[data-f]").forEach(b => b.onclick = () => {
    const c = $("#conf");
    if (c && !c.checked) { $("#em").innerHTML = `<span class="err">Marque a confirmação para exportar com avisos pendentes.</span>`; c.focus(); return; }
    location.href = `/api/projects/${P.id}/export.${b.dataset.f}${c ? "?confirm=true" : ""}`;
  });
  focusMain();
}

route();
