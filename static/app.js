"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const estado = { perfis: [], perfilId: null, laudo: null, arquivo: null, historico: [] };

const SELO = {
  normal: "✓ Dentro da referência",
  alto: "▲ Acima da referência",
  baixo: "▼ Abaixo da referência",
  alterado: "! Diferente do esperado",
  sem_referencia: "– Sem referência",
};

function selo(r) {
  if (r.critico) return `<span class="selo critico">⚠ Valor crítico</span>`;
  if (!r.situacao) return "";
  return `<span class="selo ${r.situacao}">${SELO[r.situacao]}</span>`;
}

function toast(msg, erro = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = erro ? "erro" : "";
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.hidden = true), erro ? 7000 : 3500);
}

async function api(url, opts = {}) {
  const r = await fetch(url, opts);
  const corpo = r.headers.get("content-type")?.includes("json") ? await r.json() : await r.text();
  if (!r.ok) {
    const d = corpo?.detail;
    const msg = typeof d === "string" ? d : d?.mensagem || (Array.isArray(d) ? d.map((x) => x.msg).join("; ") : "Erro inesperado");
    throw new Error(msg);
  }
  return corpo;
}

function mostrar(view) {
  $$(".view").forEach((v) => (v.hidden = v.id !== `view-${view}`));
  $$("nav button").forEach((b) => b.classList.toggle("ativo", b.dataset.view === view));
  window.scrollTo(0, 0);
  if (view === "laudos") carregarLaudos();
  if (view === "evolucao") carregarEvolucao();
}

// ------------------------------------------------------------------ perfis
async function carregarPerfis(selecionar) {
  estado.perfis = await api("/api/perfis");
  const sel = $("#sel-perfil");
  sel.innerHTML = estado.perfis.map((p) => `<option value="${p.id}">${esc(p.nome)}</option>`).join("") +
    `<option value="novo">+ Novo perfil…</option>`;
  if (!estado.perfis.length) {
    estado.perfilId = null;
    $("#btn-cancelar-perfil").hidden = true;
    return mostrar("perfil");
  }
  $("#btn-cancelar-perfil").hidden = false;
  const salvo = Number(selecionar || localStorage.getItem("perfil"));
  estado.perfilId = estado.perfis.some((p) => p.id === salvo) ? salvo : estado.perfis[0].id;
  sel.value = estado.perfilId;
  localStorage.setItem("perfil", estado.perfilId);
}

$("#sel-perfil").addEventListener("change", (e) => {
  if (e.target.value === "novo") {
    e.target.value = estado.perfilId ?? "";
    return mostrar("perfil");
  }
  estado.perfilId = Number(e.target.value);
  localStorage.setItem("perfil", estado.perfilId);
  mostrar("laudos");
});

$("#form-perfil").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  try {
    const p = await api("/api/perfis", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        nome: f.get("nome"), data_nascimento: f.get("data_nascimento"), sexo: f.get("sexo"),
        consentimento: f.get("consentimento") === "on",
      }),
    });
    e.target.reset();
    await carregarPerfis(p.id);
    mostrar("enviar");
  } catch (err) { toast(err.message, true); }
});
$("#btn-cancelar-perfil").addEventListener("click", () => mostrar("laudos"));

$("#btn-excluir-perfil").addEventListener("click", async () => {
  const p = estado.perfis.find((x) => x.id === estado.perfilId);
  if (!p || !confirm(`Excluir o perfil "${p.nome}" e TODOS os laudos e dados dele? Isso não pode ser desfeito.`)) return;
  await api(`/api/perfis/${p.id}`, { method: "DELETE" });
  localStorage.removeItem("perfil");
  toast("Perfil e dados excluídos.");
  await carregarPerfis();
  if (estado.perfilId) mostrar("laudos");
});

// ------------------------------------------------------------------ lista
async function carregarLaudos() {
  if (!estado.perfilId) return;
  const laudos = await api(`/api/perfis/${estado.perfilId}/laudos`);
  const el = $("#lista-laudos");
  if (!laudos.length) {
    el.innerHTML = `<div class="vazio">Nenhum laudo ainda. Envie o PDF ou uma foto do seu primeiro laudo.</div>`;
    return;
  }
  el.innerHTML = laudos.map((l) => {
    const titulo = l.tipo && l.tipo !== "laboratorial" ? (l.titulo || "Laudo descritivo") : `${l.qtd_resultados} resultados`;
    let situacao = "";
    if (l.status === "erro") situacao = `<span class="selo alterado">Erro na leitura</span>`;
    else if (l.qtd_criticos) situacao = `<span class="selo critico">⚠ ${l.qtd_criticos} valor(es) crítico(s)</span>`;
    else if (l.qtd_alterados) situacao = `<span class="selo alto">${l.qtd_alterados} fora da referência</span>`;
    else if (l.qtd_resultados) situacao = `<span class="selo normal">✓ Todos dentro da referência</span>`;
    const etapa = { lido: "Aguardando conferência", conferido: "Conferido", interpretado: "Interpretado", erro: esc(l.erro || "") }[l.status];
    return `<div class="laudo-item" data-id="${l.id}" data-status="${l.status}">
      <div><div class="titulo">${esc(l.data_coleta || l.criado_em.slice(0, 10))} · ${esc(l.laboratorio || l.arquivo_nome || "Laudo")}</div>
      <div class="muted">${esc(titulo)} · ${etapa}</div></div>
      <div>${situacao}</div></div>`;
  }).join("");
  $$(".laudo-item", el).forEach((it) => it.addEventListener("click", () => abrirLaudo(Number(it.dataset.id))));
}

async function abrirLaudo(id) {
  const reg = await api(`/api/laudos/${id}`);
  estado.laudo = reg;
  if (reg.status === "erro") return toast(`Este laudo não foi lido: ${reg.erro}`, true);
  if (reg.interpretacao) return mostrarInterpretacao();
  mostrarConferencia();
}

// ------------------------------------------------------------------ envio
async function carregarStatus() {
  const s = await api("/api/status");
  const sel = $("#sel-extrator");
  sel.innerHTML = s.extratores.map((e) => `<option value="${e.nome}" ${e.disponivel ? "" : "disabled"}>${esc(e.descricao)}${e.disponivel ? "" : " (indisponível)"}</option>`).join("");
  const claude = s.extratores.find((e) => e.nome === "claude");
  sel.value = claude?.disponivel ? "claude" : "texto";
  $("#extrator-aviso").textContent = s.claude ? "" : "Claude indisponível: " + s.motivo + " Por enquanto, só a leitura por regras e a interpretação básica funcionam.";
  estado.claude = s.claude;
}

function escolherArquivo(f) {
  if (!f) return;
  estado.arquivo = f;
  $("#arquivo-nome").textContent = f.name || "imagem colada";
  const mini = $("#mini");
  if (f.type.startsWith("image/")) {
    mini.src = URL.createObjectURL(f);
    mini.hidden = false;
  } else mini.hidden = true;
}
["#arquivo", "#camera"].forEach((s) => $(s).addEventListener("change", (e) => escolherArquivo(e.target.files[0])));
const dz = $("#dropzone");
dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("sobre"); });
dz.addEventListener("dragleave", () => dz.classList.remove("sobre"));
dz.addEventListener("drop", (e) => { e.preventDefault(); dz.classList.remove("sobre"); escolherArquivo(e.dataTransfer.files[0]); });
document.addEventListener("paste", (e) => {
  if ($("#view-enviar").hidden) return;
  const img = [...(e.clipboardData?.files || [])].find((f) => f.type.startsWith("image/"));
  if (img) escolherArquivo(img);
});

$("#form-upload").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData();
  fd.append("perfil_id", estado.perfilId);
  fd.append("extrator", $("#sel-extrator").value);
  const texto = e.target.texto.value;
  if (estado.arquivo) fd.append("arquivo", estado.arquivo, estado.arquivo.name || "imagem.png");
  else if (texto.trim()) fd.append("texto", texto);
  else return toast("Escolha um arquivo, tire uma foto ou cole o texto do laudo.", true);
  $("#btn-ler").disabled = true;
  $("#lendo").hidden = false;
  try {
    estado.laudo = await api("/api/laudos", { method: "POST", body: fd });
    estado.arquivo = null;
    e.target.reset();
    $("#arquivo-nome").textContent = "";
    $("#mini").hidden = true;
    mostrarConferencia();
  } catch (err) { toast(err.message, true); }
  finally { $("#btn-ler").disabled = false; $("#lendo").hidden = true; }
});

// ------------------------------------------------------------------ conferência
function getPath(obj, path) { return path.split(".").reduce((o, k) => (o ? o[k] : undefined), obj); }
function setPath(obj, path, v) {
  const ks = path.split(".");
  const last = ks.pop();
  ks.reduce((o, k) => (o[k] ??= {}), obj)[last] = v;
}

function previewDocumento(reg) {
  const box = $("#doc-preview");
  const url = `/api/laudos/${reg.id}/arquivo`;
  const mime = reg.mime || "";
  if (mime.startsWith("image/")) {
    box.innerHTML = `<img src="${url}" alt="Laudo enviado">`;
    $("img", box).addEventListener("click", (e) => e.target.classList.toggle("zoom"));
  } else if (mime === "application/pdf") box.innerHTML = `<iframe src="${url}" title="Laudo em PDF"></iframe>`;
  else fetch(url).then((r) => r.text()).then((t) => (box.innerHTML = `<pre>${esc(t)}</pre>`));
}

function linhaResultado(r, i, incertos) {
  const inc = (c) => (incertos.has(`resultados[${i}].${c}`) || incertos.has(`resultados[${i}]`) ? "incerto" : "");
  return `<tr data-i="${i}">
    <td><input data-r="analito" value="${esc(r.analito)}" class="${inc("analito")}" aria-label="Exame">
      <small>${esc(r.exame && r.exame !== r.analito ? r.exame : "")}${r.nome_padrao && r.nome_padrao !== r.analito ? ` → ${esc(r.nome_padrao)}` : ""}</small></td>
    <td><input data-r="valor" value="${esc(r.valor)}" class="${inc("valor")}" aria-label="Resultado"></td>
    <td><input data-r="unidade" value="${esc(r.unidade)}" class="${inc("unidade")}" aria-label="Unidade"></td>
    <td><input data-r="referencia" value="${esc(r.referencia)}" class="${inc("referencia")}" aria-label="Referência"></td>
    <td>${selo(r)}</td>
    <td><button type="button" class="mini" data-remover title="Remover linha" aria-label="Remover">✕</button></td>
  </tr>`;
}

function mostrarConferencia() {
  const reg = estado.laudo;
  const d = reg.dados;
  previewDocumento(reg);
  const incertos = new Set(d.campos_incertos || []);
  $$("#form-conferir [data-c]").forEach((el) => {
    el.value = getPath(d, el.dataset.c) ?? "";
    el.classList.toggle("incerto", incertos.has(el.dataset.c));
  });
  const alertas = [...(d.alertas_leitura || [])];
  if (d.legibilidade === "ruim") alertas.unshift("A imagem estava difícil de ler. Confira cada valor com atenção ou envie uma foto melhor.");
  $("#alertas-leitura").innerHTML = alertas.length
    ? `<div class="alerta amarelo"><strong>Confira:</strong><ul>${alertas.map((a) => `<li>${esc(a)}</li>`).join("")}</ul></div>` : "";
  desenharResultados(d.resultados, incertos);
  $("#bloco-descritivo").hidden = d.tipo === "laboratorial" && !d.conclusao && !d.achados;
  mostrar("conferir");
}

function desenharResultados(resultados, incertos = new Set()) {
  const tb = $("#tab-resultados tbody");
  tb.innerHTML = resultados.map((r, i) => linhaResultado(r, i, incertos)).join("") ||
    `<tr><td colspan="6" class="muted">Nenhum resultado numérico. Para laudos de imagem, confira o texto abaixo.</td></tr>`;
  $$("[data-remover]", tb).forEach((b) => b.addEventListener("click", () => {
    const dados = coletarConferencia();
    dados.resultados.splice(Number(b.closest("tr").dataset.i), 1);
    estado.laudo.dados = dados;
    desenharResultados(dados.resultados);
  }));
}

$("#btn-add-res").addEventListener("click", () => {
  const dados = coletarConferencia();
  dados.resultados.push({ exame: "", analito: "", valor: "", unidade: "", referencia: "" });
  estado.laudo.dados = dados;
  desenharResultados(dados.resultados);
  $("#tab-resultados tbody tr:last-child input").focus();
});

$("#form-conferir [data-c='tipo']").addEventListener("change", (e) => { $("#bloco-descritivo").hidden = e.target.value === "laboratorial"; });

function coletarConferencia() {
  const d = structuredClone(estado.laudo.dados);
  $$("#form-conferir [data-c]").forEach((el) => setPath(d, el.dataset.c, el.value.trim()));
  const linhas = $$("#tab-resultados tbody tr[data-i]");
  d.resultados = linhas.map((tr) => {
    const orig = d.resultados[Number(tr.dataset.i)] || {};
    const r = { ...orig };
    $$("[data-r]", tr).forEach((el) => (r[el.dataset.r] = el.value.trim()));
    if (r.referencia !== orig.referencia) { r.ref_min = null; r.ref_max = null; }
    return r;
  }).filter((r) => r.analito || r.valor);
  d.campos_incertos = [];
  return d;
}

async function salvarEInterpretar(basico) {
  const dados = coletarConferencia();
  $("#btn-interpretar").disabled = $("#btn-basico").disabled = true;
  $("#interpretando").hidden = false;
  try {
    await api(`/api/laudos/${estado.laudo.id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(dados) });
    estado.laudo = await api(`/api/laudos/${estado.laudo.id}/interpretar${basico ? "?basico=true" : ""}`, { method: "POST" });
    mostrarInterpretacao();
  } catch (err) { toast(err.message, true); }
  finally { $("#btn-interpretar").disabled = $("#btn-basico").disabled = false; $("#interpretando").hidden = true; }
}
$("#form-conferir").addEventListener("submit", (e) => { e.preventDefault(); salvarEInterpretar(!estado.claude); });
$("#btn-basico").addEventListener("click", () => salvarEInterpretar(true));

// ------------------------------------------------------------------ interpretação
const lista = (itens) => `<ul class="secao-lista">${itens.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;

function cartaoItem(item, r) {
  const fora = r && ["alto", "baixo", "alterado"].includes(r.situacao);
  const cls = r?.critico ? "critico" : fora ? "fora" : "";
  const valor = r ? `<div class="valor"><strong>${esc(r.valor)} ${esc(r.unidade)}</strong>
      ${r.referencia ? `<small> · referência: ${esc(r.referencia)}</small>` : ""}</div>` : "";
  return `<div class="item ${cls}">
    <div class="titulo-item"><strong>${esc(item.titulo || r?.analito || "")}</strong>${r ? selo(r) : ""}</div>
    ${valor}
    ${item.o_que_e ? `<p><strong>O que é:</strong> ${esc(item.o_que_e)}</p>` : ""}
    ${item.seu_resultado ? `<p><strong>Seu resultado:</strong> ${esc(item.seu_resultado)}</p>` : ""}
    ${item.possiveis_causas?.length ? `<p><strong>Causas comuns de alteração</strong> (nem sempre são doença):</p>${lista(item.possiveis_causas)}` : ""}
  </div>`;
}

function mostrarInterpretacao() {
  const reg = estado.laudo;
  const d = reg.dados;
  const it = reg.interpretacao;
  const res = d.resultados || [];
  const porIndice = new Map(it.itens.map((x) => [x.indice, x]));
  const alterados = [], normais = [];
  res.forEach((r, i) => {
    const item = porIndice.get(i) || { titulo: r.nome_padrao || r.analito };
    (r.critico || ["alto", "baixo", "alterado"].includes(r.situacao) ? alterados : normais).push(cartaoItem(item, r));
  });
  const descritivos = it.itens.filter((x) => x.indice === -1).map((x) => cartaoItem(x, null));

  $("#relatorio").innerHTML = `
    <div class="cab">
      <div><h2>${esc(d.titulo_exame || "Seu laudo explicado")}</h2>
        <div class="muted">${esc(d.laboratorio)}${d.data_coleta ? ` · coleta em ${esc(d.data_coleta)}` : ""}</div></div>
      <div class="botoes-relatorio">
        <button id="btn-editar">Corrigir transcrição</button>
        <button id="btn-imprimir">Imprimir / salvar PDF</button>
        <button id="btn-excluir-laudo">Excluir laudo</button>
      </div>
    </div>
    ${it.procurar_atendimento?.length ? `<div class="alerta vermelho"><strong>⚠ Procure atendimento médico</strong>${lista(it.procurar_atendimento)}</div>` : ""}
    <div class="resumo">${esc(it.resumo)}</div>
    ${it.destaques?.length ? `<h3>Pontos principais</h3>${lista(it.destaques)}` : ""}
    ${descritivos.length ? `<h3>O que o laudo diz</h3><div class="itens">${descritivos.join("")}</div>` : ""}
    ${alterados.length ? `<h3>Resultados que merecem atenção (${alterados.length})</h3><div class="itens">${alterados.join("")}</div>` : ""}
    ${normais.length ? `<details class="normais" ${alterados.length ? "" : "open"}><summary>Resultados dentro da referência ou sem referência (${normais.length})</summary><div class="itens">${normais.join("")}</div></details>` : ""}
    ${it.perguntas_medico?.length ? `<h3>Perguntas para levar ao seu médico</h3>${lista(it.perguntas_medico)}
      <button class="mini" id="btn-copiar">Copiar perguntas</button>` : ""}
    ${it.exames_para_conversar?.length ? `<h3>Exames que você pode conversar com seu médico</h3>
      <p class="muted">Sugestões para a conversa, não um pedido de exame. Só o médico decide o que é necessário.</p>
      <ul class="secao-lista">${it.exames_para_conversar.map((x) => `<li><strong>${esc(x.exame)}</strong>: ${esc(x.motivo)}</li>`).join("")}</ul>` : ""}
    ${it.habitos?.length ? `<h3>Hábitos que costumam ajudar</h3>${lista(it.habitos)}` : ""}
    ${it.acompanhamento ? `<h3>Acompanhamento</h3><p>${esc(it.acompanhamento)}</p>` : ""}
    <p class="aviso-legal">${esc(it.aviso)} ${it.modo === "basico" ? "Interpretação básica, gerada sem IA." : "Explicação gerada com IA (Claude) a partir da transcrição que você conferiu; a classificação de cada valor e os alertas de valores críticos são calculados por regras, pela referência do próprio laudo."}</p>`;

  $("#btn-editar").addEventListener("click", mostrarConferencia);
  $("#btn-imprimir").addEventListener("click", () => window.print());
  $("#btn-excluir-laudo").addEventListener("click", async () => {
    if (!confirm("Excluir este laudo e o arquivo enviado?")) return;
    await api(`/api/laudos/${reg.id}`, { method: "DELETE" });
    toast("Laudo excluído.");
    mostrar("laudos");
  });
  $("#btn-copiar")?.addEventListener("click", () => {
    navigator.clipboard.writeText(it.perguntas_medico.map((p) => `- ${p}`).join("\n")).then(() => toast("Perguntas copiadas."));
  });
  mostrar("interpretacao");
}

// ------------------------------------------------------------------ evolução
async function carregarEvolucao() {
  if (!estado.perfilId) return;
  estado.historico = await api(`/api/perfis/${estado.perfilId}/historico`);
  desenharEvolucao();
}
$("#filtro-evolucao").addEventListener("change", desenharEvolucao);

const fmt = (v) => (v == null ? "" : Number(v).toLocaleString("pt-BR", { maximumFractionDigits: 2 }));
const dataBR = (iso) => (iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}` : "sem data");

function desenharEvolucao() {
  const filtro = $("#filtro-evolucao").value;
  const grupos = estado.historico.filter((g) => filtro === "todos" || g.pontos.some((p) => ["alto", "baixo", "alterado"].includes(p.situacao)));
  const el = $("#graficos");
  if (!grupos.length) {
    el.innerHTML = `<div class="vazio">${estado.historico.length ? "Nenhum exame fora da referência." : "Os gráficos aparecem depois que você conferir pelo menos um laudo."}</div>`;
    return;
  }
  el.innerHTML = grupos.map((g, gi) => `
    <div class="grafico">
      <h4>${esc(g.nome)}</h4>
      <div class="sub">${esc(g.categoria)} · último: <strong>${esc(g.ultimo.valor)} ${esc(g.unidade || "")}</strong> ${selo(g.ultimo)}</div>
      ${grafico(g, gi)}
      <details><summary>Ver valores (${g.pontos.length})</summary>
        <table><thead><tr><th>Coleta</th><th>Resultado</th><th>Referência</th><th>Situação</th></tr></thead><tbody>
        ${g.pontos.map((p) => `<tr><td>${dataBR(p.data_coleta)}</td><td>${esc(p.valor)} ${esc(p.unidade)}</td>
          <td>${p.ref_min != null ? fmt(p.ref_min) : ""}${p.ref_min != null && p.ref_max != null ? " a " : ""}${p.ref_max != null ? (p.ref_min == null ? "até " : "") + fmt(p.ref_max) : ""}</td>
          <td>${SELO[p.situacao] || ""}</td></tr>`).join("")}
        </tbody></table></details>
      ${g.descricao ? `<p class="muted" style="font-size:13px;margin:6px 0 0">${esc(g.descricao)}</p>` : ""}
    </div>`).join("");
  $$(".grafico svg").forEach(ligarTooltip);
}

function grafico(g, gi) {
  // um gráfico por exame (série única: o título dá nome à série, sem legenda);
  // só pontos com a mesma unidade do último resultado, para não misturar escalas
  const pts = g.pontos.filter((p) => p.valor_numerico != null && (p.unidade || "") === (g.unidade || ""));
  if (!pts.length) return `<p class="muted">Resultado não numérico; veja os valores abaixo.</p>`;
  const W = 340, H = 150, m = { l: 44, r: 12, t: 10, b: 24 };
  const ultimo = pts[pts.length - 1];
  const vals = pts.map((p) => p.valor_numerico).concat([ultimo.ref_min, ultimo.ref_max].filter((v) => v != null));
  let lo = Math.min(...vals), hi = Math.max(...vals);
  const folga = (hi - lo || Math.abs(hi) || 1) * 0.15;
  lo = Math.max(0, lo - folga); hi = hi + folga;
  // marcas "redondas" no eixo (1, 2, 2,5 ou 5 × 10^n)
  const bruto = (hi - lo) / 2, pot = 10 ** Math.floor(Math.log10(bruto));
  const passo = [1, 2, 2.5, 5, 10].map((k) => k * pot).find((v) => v >= bruto);
  lo = Math.floor(lo / passo) * passo; hi = Math.ceil(hi / passo) * passo;
  const x = (i) => (pts.length === 1 ? m.l + (W - m.l - m.r) / 2 : m.l + (i * (W - m.l - m.r)) / (pts.length - 1));
  const y = (v) => m.t + (H - m.t - m.b) * (1 - (v - lo) / (hi - lo));
  // faixa só com limite superior ("inferior a 190") vai até a base; só com inferior, até o topo
  const rmin = ultimo.ref_min != null ? y(ultimo.ref_min) : H - m.b;
  const rmax = ultimo.ref_max != null ? y(ultimo.ref_max) : m.t;
  const ticks = [];
  for (let t = lo; t <= hi + passo / 2; t += passo) ticks.push(t);
  const linha = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.valor_numerico).toFixed(1)}`).join(" ");
  const titulo = `Evolução de ${g.nome}: ${pts.map((p) => `${dataBR(p.data_coleta)} ${fmt(p.valor_numerico)}`).join(", ")}`;
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(titulo)}" data-g="${gi}">
    ${ticks.map((t) => `<line x1="${m.l}" x2="${W - m.r}" y1="${y(t)}" y2="${y(t)}" stroke="#eceae6" stroke-width="1"/>
      <text x="${m.l - 6}" y="${y(t) + 4}" text-anchor="end">${fmt(t)}</text>`).join("")}
    ${ultimo.ref_min != null || ultimo.ref_max != null ? `<rect x="${m.l}" width="${W - m.l - m.r}" y="${Math.min(rmin, rmax)}" height="${Math.abs(rmax - rmin)}" fill="rgba(12,163,12,.12)"/>
      <text x="${W - m.r - 4}" y="${Math.min(rmin, rmax) + 12}" text-anchor="end">referência</text>` : ""}
    <line class="mira" x1="0" x2="0" y1="${m.t}" y2="${H - m.b}" stroke="#9a9893" stroke-width="1" visibility="hidden"/>
    ${pts.length > 1 ? `<path d="${linha}" fill="none" stroke="#2a78d6" stroke-width="2" stroke-linejoin="round"/>` : ""}
    ${pts.map((p, i) => {
      const fora = ["alto", "baixo", "alterado"].includes(p.situacao);
      return `<circle cx="${x(i)}" cy="${y(p.valor_numerico)}" r="${fora ? 5 : 4}" fill="${fora ? "#d03b3b" : "#2a78d6"}" stroke="#fcfcfb" stroke-width="2"/>`;
    }).join("")}
    ${pts.map((p, i) => (i === 0 || i === pts.length - 1 || pts.length <= 4 ? `<text x="${x(i)}" y="${H - 6}" text-anchor="${pts.length === 1 ? "middle" : i === 0 ? "start" : i === pts.length - 1 ? "end" : "middle"}">${dataBR(p.data_coleta)}</text>` : "")).join("")}
    <rect class="alvo" x="${m.l}" y="0" width="${W - m.l - m.r}" height="${H}" fill="transparent"/>
  </svg>`;
}

function ligarTooltip(svg) {
  const g = estado.historico.filter((h) => $("#filtro-evolucao").value === "todos" || h.pontos.some((p) => ["alto", "baixo", "alterado"].includes(p.situacao)))[Number(svg.dataset.g)];
  const pts = g.pontos.filter((p) => p.valor_numerico != null && (p.unidade || "") === (g.unidade || ""));
  const circs = $$("circle", svg);
  const mira = $(".mira", svg);
  const tip = $("#tooltip");
  const alvo = $(".alvo", svg);
  alvo.addEventListener("pointermove", (e) => {
    const pt = svg.createSVGPoint();
    pt.x = e.clientX; pt.y = e.clientY;
    const loc = pt.matrixTransform(svg.getScreenCTM().inverse());
    let mais = 0;
    circs.forEach((c, i) => { if (Math.abs(c.cx.baseVal.value - loc.x) < Math.abs(circs[mais].cx.baseVal.value - loc.x)) mais = i; });
    const c = circs[mais], p = pts[mais];
    mira.setAttribute("x1", c.cx.baseVal.value); mira.setAttribute("x2", c.cx.baseVal.value);
    mira.setAttribute("visibility", "visible");
    tip.innerHTML = `<strong>${esc(p.valor)} ${esc(p.unidade)}</strong><br>${dataBR(p.data_coleta)}<br>${SELO[p.situacao] || ""}`;
    tip.hidden = false;
    const r = c.getBoundingClientRect();
    tip.style.left = `${Math.min(r.right + 10, window.innerWidth - tip.offsetWidth - 8)}px`;
    tip.style.top = `${r.top - tip.offsetHeight - 6}px`;
  });
  alvo.addEventListener("pointerleave", () => { tip.hidden = true; mira.setAttribute("visibility", "hidden"); });
}

// ------------------------------------------------------------------ início
$$("nav button").forEach((b) => b.addEventListener("click", () => estado.perfilId ? mostrar(b.dataset.view) : mostrar("perfil")));
$$("[data-ir]").forEach((b) => b.addEventListener("click", () => mostrar(b.dataset.ir)));

(async () => {
  try {
    await carregarStatus();
    await carregarPerfis();
    if (estado.perfilId) mostrar("laudos");
  } catch (err) { toast(err.message, true); }
})();
