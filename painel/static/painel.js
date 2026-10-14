/* Painel da central: lê /api/painel e /api/agora e desenha hero, KPIs, gráficos e tabelas.
   Sem framework: só fetch, template strings e Plotly. */
(function () {
  "use strict";

  // ------------------------------------------------------------------ tokens
  // Cores tiradas do design system e validadas para o fundo #121317 (daltonismo e contraste).
  const COR = {
    categoria: { alarme: "#e11d48", tecnico: "#d97706", informativo: "#3b82f6" },
    tecnico: { comunicacao: "#059669", energia: "#b45309", bateria: "#a855f7" },
    serie: "#10b981", destaque: "#e11d48", pico: "#b45309",
    esperado: "#facc15", texto: "#737373", eixo: "#525252", grade: "rgba(255,255,255,0.05)",
    superficie: "#121317", tooltip: "#1a1b20",
  };
  const ROTULO = {
    categoria: { alarme: "Alarme", tecnico: "Técnico", informativo: "Informativo" },
    tecnico: { comunicacao: "Comunicação", energia: "Energia", bateria: "Bateria" },
    prioridade: { critica: "Crítica", alta: "Alta", media: "Média", baixa: "Baixa", informativa: "Informativa" },
    status: { aberto: "Aberto", em_atendimento: "Em atendimento", encerrado: "Encerrado", registrado: "Registrado" },
    tipo: { residencial: "Residencial", comercial: "Comercial", agencia_bancaria: "Agência bancária", industrial: "Industrial" },
    resultado: { falso_alarme: "Falso alarme", cliente_contatado: "Cliente contatado", tecnico_agendado: "Técnico agendado",
      sem_contato: "Sem contato", viatura_enviada: "Viatura enviada", policia_acionada: "Polícia acionada", bombeiros_acionados: "Bombeiros acionados" },
    turno: { dia: "Dia", noite: "Noite" },
    problema: {
      data_hora_formato_br: "Data em dd/mm/aaaa", data_hora_sem_fuso: "Data sem fuso",
      codigo_evento_grafia: "Código com caixa/espaço", codigo_evento_desconhecido: "Código desconhecido",
      status_grafia: "Status com caixa", status_sinonimo: "Status 'fechado'",
      operador_grafia: "Operador com caixa/espaço", operador_nome_incompleto: "Operador só com 1º nome",
      tempo_texto: "Tempo como texto", tempo_negativo: "Tempo negativo", tempo_ausente: "Tempo ausente",
      cliente_id_grafia: "Id de cliente minúsculo", cliente_desconhecido: "Cliente inexistente",
      cidade_grafia: "Cidade com grafia variada", nome_caixa_alta: "Nome em caixa alta",
    },
  };
  const DIA_SEMANA = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"];
  const FONTE = "Geist, Inter, sans-serif";

  const LAYOUT = {
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: FONTE, size: 11, color: COR.texto },
    margin: { l: 8, r: 8, t: 8, b: 28 }, showlegend: false, bargap: 0.35,
    hovermode: "closest", dragmode: false,
    hoverlabel: { bgcolor: COR.tooltip, bordercolor: "rgba(255,255,255,0.1)", font: { family: FONTE, size: 11, color: "#e5e5e5" }, align: "left" },
    xaxis: { gridcolor: "rgba(0,0,0,0)", zeroline: false, linecolor: "rgba(0,0,0,0)", tickfont: { size: 10, color: COR.eixo }, fixedrange: true, automargin: true },
    yaxis: { gridcolor: COR.grade, zeroline: false, linecolor: "rgba(0,0,0,0)", tickfont: { size: 10, color: COR.eixo }, fixedrange: true, automargin: true },
    transition: { duration: 500, easing: "cubic-out" },
  };
  const CONFIG = { displayModeBar: false, responsive: true, doubleClick: false, scrollZoom: false };

  // ------------------------------------------------------------------ utilidades
  const $ = (id) => document.getElementById(id);
  const fmtN = (n) => (n == null ? "–" : Number(n).toLocaleString("pt-BR"));
  const fmtPct = (x, casas = 0) => (x == null || isNaN(x) ? "–" : (x * 100).toLocaleString("pt-BR", { maximumFractionDigits: casas, minimumFractionDigits: casas }) + "%");
  const fmtDur = (seg) => {
    if (seg == null || isNaN(seg)) return "–";
    seg = Math.round(seg);
    if (seg < 60) return `${seg} s`;
    const m = Math.floor(seg / 60), s = seg % 60;
    if (m < 60) return s ? `${m} min ${String(s).padStart(2, "0")} s` : `${m} min`;
    return `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")} min`;
  };
  const fmtData = (iso) => { const [a, m, d] = iso.slice(0, 10).split("-"); return `${d}/${m}/${a}`; };
  const fmtDataCurta = (iso) => { const [, m, d] = iso.slice(0, 10).split("-"); return `${d}/${m}`; };
  const fmtHora = (dh) => dh.slice(11, 16);
  const fmtTempoAtras = (min) => (min < 1 ? "agora" : min < 60 ? `há ${min} min` : min < 1440 ? `há ${Math.floor(min / 60)} h ${min % 60} min` : `há ${Math.floor(min / 1440)} d`);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const addDias = (iso, n) => { const d = new Date(iso + "T00:00:00"); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); };
  const diasEntre = (a, b) => Math.round((new Date(b + "T00:00:00") - new Date(a + "T00:00:00")) / 86400000) + 1;
  const mediana = (v) => { const s = [...v].sort((a, b) => a - b); const m = Math.floor(s.length / 2); return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };

  // Contagem animada (design: count-up do cartão de métrica, easeOutQuart).
  function contar(el, alvo, duracao = 1400, formatar = fmtN) {
    const de = Number(el.dataset.valor || 0);
    el.dataset.valor = alvo;
    if (!isFinite(alvo)) { el.textContent = formatar(alvo); return; }
    const inicio = performance.now();
    const passo = (t) => {
      const p = Math.min(1, (t - inicio) / duracao);
      const e = 1 - Math.pow(1 - p, 4);
      el.textContent = formatar(Math.round(de + (alvo - de) * e));
      if (p < 1) requestAnimationFrame(passo);
    };
    requestAnimationFrame(passo);
  }

  function chip(delta, { bomQuandoSobe = false, sufixo = "" } = {}) {
    if (delta == null || !isFinite(delta)) return `<span class="chip chip-neutro">sem base</span>`;
    const sobe = delta > 0.0005, desce = delta < -0.0005;
    const classe = !sobe && !desce ? "chip-neutro" : (sobe === bomQuandoSobe ? "chip-bom" : "chip-ruim");
    const seta = sobe ? "↑" : desce ? "↓" : "→";
    return `<span class="chip ${classe}" title="em relação ao período anterior de mesmo tamanho">${seta} ${fmtPct(Math.abs(delta), 1)}${sufixo}</span>`;
  }
  const variacao = (atual, anterior) => (anterior ? (atual - anterior) / anterior : null);

  function vazio(el, msg = "Sem dados no período") {
    Plotly.purge(el);
    el.innerHTML = `<div class="vazio">${msg}</div>`;
    el.classList.add("pronto");
  }
  function plot(el, dados, layoutExtra, config) {
    if (!el.classList.contains("js-plotly-plot")) el.innerHTML = "";
    const layout = { ...LAYOUT, ...layoutExtra };
    layout.xaxis = { ...LAYOUT.xaxis, ...(layoutExtra.xaxis || {}) };
    layout.yaxis = { ...LAYOUT.yaxis, ...(layoutExtra.yaxis || {}) };
    return Plotly.react(el, dados, layout, config || CONFIG).then(() => el.classList.add("pronto"));
  }
  function legenda(el, mapaCor, mapaRotulo, chaves) {
    el.innerHTML = chaves.map((k) => `<span class="leg-item"><span class="leg-cor" style="background:${mapaCor[k]}"></span>${mapaRotulo[k] || k}</span>`).join("");
  }
  const insight = (titulo, html, aviso = false) => `
    <div class="insight ${aviso ? "aviso" : ""}">
      <div class="insight-icone"><svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5"/><path d="M9 18h6"/><path d="M10 22h4"/></svg></div>
      <div><h4>${titulo}</h4><p>${html}</p></div>
    </div>`;

  // ------------------------------------------------------------------ filtros
  const OPC = window.PAINEL.opcoes;
  const estado = { inicio: null, fim: null, cidade: "", tipo: "" };

  function lerURL() {
    const q = new URLSearchParams(location.search);
    const max = OPC.data_maxima, dias = window.PAINEL.dias_padrao;
    estado.fim = q.get("fim") || max;
    estado.inicio = q.get("inicio") || addDias(max, -(dias - 1));
    estado.cidade = q.get("cidade") || "";
    estado.tipo = q.get("tipo") || "";
  }
  function gravarURL() {
    const q = new URLSearchParams();
    q.set("inicio", estado.inicio); q.set("fim", estado.fim);
    if (estado.cidade) q.set("cidade", estado.cidade);
    if (estado.tipo) q.set("tipo", estado.tipo);
    history.replaceState(null, "", "?" + q.toString() + location.hash);
  }
  function refletirFiltros() {
    $("f-inicio").value = estado.inicio;
    $("f-fim").value = estado.fim;
    $("f-cidade").value = estado.cidade;
    $("f-tipo").value = estado.tipo;
    const dias = diasEntre(estado.inicio, estado.fim);
    const tudo = estado.inicio <= OPC.data_minima && estado.fim >= OPC.data_maxima;
    document.querySelectorAll("#periodos .seg").forEach((b) => {
      const d = Number(b.dataset.dias);
      b.classList.toggle("ativo", d === 0 ? tudo : (!tudo && estado.fim === OPC.data_maxima && dias === d));
    });
    const padrao = !estado.cidade && !estado.tipo && estado.fim === OPC.data_maxima && dias === window.PAINEL.dias_padrao;
    $("f-limpar").classList.toggle("inativo", padrao);
  }
  function ligarFiltros() {
    document.querySelectorAll("#periodos .seg").forEach((b) => b.addEventListener("click", () => {
      const d = Number(b.dataset.dias);
      estado.fim = OPC.data_maxima;
      estado.inicio = d === 0 ? OPC.data_minima : addDias(OPC.data_maxima, -(d - 1));
      if (estado.inicio < OPC.data_minima) estado.inicio = OPC.data_minima;
      aplicar();
    }));
    $("f-inicio").addEventListener("change", (e) => { if (e.target.value) { estado.inicio = e.target.value; if (estado.inicio > estado.fim) estado.fim = estado.inicio; aplicar(); } });
    $("f-fim").addEventListener("change", (e) => { if (e.target.value) { estado.fim = e.target.value; if (estado.fim < estado.inicio) estado.inicio = estado.fim; aplicar(); } });
    $("f-cidade").addEventListener("change", (e) => { estado.cidade = e.target.value; aplicar(); });
    $("f-tipo").addEventListener("change", (e) => { estado.tipo = e.target.value; aplicar(); });
    $("f-limpar").addEventListener("click", () => {
      estado.cidade = ""; estado.tipo = ""; estado.fim = OPC.data_maxima;
      estado.inicio = addDias(OPC.data_maxima, -(window.PAINEL.dias_padrao - 1));
      aplicar();
    });
    $("btn-atualizar").addEventListener("click", () => aplicar());
    // o modo monitoramento herda cidade e tipo do painel
    const ligarMonitor = () => { const q = query(false); ["link-monitor", "link-monitor-2"].forEach((id) => { const a = $(id); if (a) a.href = "/monitoramento" + (q ? "?" + q : ""); }); };
    ["f-cidade", "f-tipo"].forEach((id) => $(id).addEventListener("change", ligarMonitor));
    $("f-limpar").addEventListener("click", ligarMonitor);
    ligarMonitor();
    $("btn-agora").addEventListener("click", () => atualizarAgora());
  }
  const query = (comPeriodo = true) => {
    const q = new URLSearchParams();
    if (comPeriodo) { q.set("inicio", estado.inicio); q.set("fim", estado.fim); }
    if (estado.cidade) q.set("cidade", estado.cidade);
    if (estado.tipo) q.set("tipo", estado.tipo);
    return q.toString();
  };

  async function aplicar() {
    refletirFiltros();
    gravarURL();
    const botao = $("btn-atualizar");
    botao.disabled = true; botao.textContent = "Atualizando…";
    try {
      const r = await fetch("/api/painel?" + query());
      const d = await r.json();
      renderTudo(d);
    } catch (e) {
      console.error(e);
      $("periodo-legenda").textContent = "Não consegui carregar os dados. O banco existe? Rode python capturar.py.";
    } finally {
      botao.disabled = false; botao.textContent = "Atualizar";
    }
  }

  // ------------------------------------------------------------------ render
  function renderTudo(d) {
    const f = d.filtros;
    const partes = [`${fmtData(f.inicio)} a ${fmtData(f.fim)} · ${diasEntre(f.inicio, f.fim)} dias`];
    if (f.cidade) partes.push(f.cidade);
    if (f.tipo) partes.push(ROTULO.tipo[f.tipo] || f.tipo);
    $("periodo-legenda").textContent = partes.join(" · ");
    $("rodape-filtros").textContent = "Recorte: " + partes.join(" · ");

    renderHero(d.resumo, d.volume_por_dia, f);
    renderResumo(d.resumo);
    renderVolume(d.volume_por_dia, f);
    renderCategorias(d.volume_por_tipo);
    renderAgora(d.abertos, d.situacao);
    renderPrioridade(d.tempo_por_prioridade);
    renderOperador(d.tempo_por_operador);
    renderTurnos(d.carga_por_turno);
    renderDesfechos(d.tempo_por_resultado);
    renderDisparos(d.ranking_disparos);
    renderTecnicos(d.problemas_tecnicos);
    renderHora(d.disparos_por_hora);
    renderEnergia(d.energia_por_dia);
    renderTestes(d.testes_ausentes);
    renderQualidade(d.qualidade);
  }

  // hero ------------------------------------------------------------------
  function renderHero(r, linhas, f) {
    const a = r.atual;
    contar($("hero-metrica"), a.eventos || 0, 2000);
    $("hero-metrica-rotulo").textContent = `eventos em ${diasEntre(f.inicio, f.fim)} dias`;
    contar($("hero-disparos"), a.disparos || 0, 1600);
    $("hero-falsos").textContent = a.disparos ? fmtPct(a.disparos_falsos / a.disparos) : "–";

    const porDia = {};
    linhas.forEach((l) => { porDia[l.dia] = (porDia[l.dia] || 0) + l.n; });
    const dias = [];
    for (let d = addDias(f.fim, -6); d <= f.fim; d = addDias(d, 1)) if (d >= f.inicio) dias.push(d);
    const vals = dias.map((d) => porDia[d] || 0);
    const maior = Math.max(1, ...vals), iMax = vals.indexOf(Math.max(...vals));
    $("hero-pico").textContent = vals.length ? `${fmtN(vals[iMax])} em ${fmtDataCurta(dias[iMax])}` : "–";

    const barras = $("hero-barras");
    barras.innerHTML = `<div class="absolute top-0 left-0 right-0 h-px border-t border-dashed border-white/20 w-full z-0"></div>` +
      dias.map((d, i) => {
        const topo = i === iMax && vals[i] > 0;
        const altura = Math.max(3, Math.round((vals[i] / maior) * 100));
        return `
        <div class="flex flex-col items-center gap-3 w-full h-full group/bar cursor-pointer z-10" title="${fmtData(d)}: ${fmtN(vals[i])} eventos">
          <div class="relative w-full h-full rounded-lg overflow-hidden bg-white/[0.02] ring-1 ring-white/5">
            <div class="absolute inset-0 opacity-10" style="background-image: repeating-linear-gradient(45deg, transparent, transparent 4px, #fff 4px, #fff 6px);"></div>
            <div class="absolute bottom-0 left-0 right-0 rounded-lg transition-all duration-500 group-hover/bar:brightness-110 animate-bar-loop ${topo ? "bg-gradient-to-t from-emerald-500 to-emerald-300 shadow-[0_0_30px_rgba(16,185,129,0.4)]" : "bg-gradient-to-t from-emerald-600 to-emerald-400 shadow-[0_0_15px_rgba(16,185,129,0.2)]"}" style="height:${altura}%; animation-delay:${i * 100}ms"></div>
          </div>
          <span class="text-xs ${topo ? "text-white" : "text-neutral-500 group-hover/bar:text-white"} transition-colors">${DIA_SEMANA[new Date(d + "T00:00:00").getDay()]}</span>
        </div>`;
      }).join("");
  }

  // 01 ---------------------------------------------------------------------
  function renderResumo(r) {
    const a = r.atual, p = r.anterior;
    contar($("k-eventos"), a.eventos || 0);
    $("c-eventos").innerHTML = chip(variacao(a.eventos, p.eventos), { bomQuandoSobe: false });
    $("n-eventos").textContent = `${fmtN(a.alarmes)} alarmes · ${fmtN(a.tecnicos)} técnicos · ${fmtN(a.eventos - a.alarmes - a.tecnicos)} informativos`;

    contar($("k-disparos"), a.disparos || 0);
    $("c-disparos").innerHTML = chip(variacao(a.disparos, p.disparos), { bomQuandoSobe: false });
    $("n-disparos").textContent = `${fmtN(a.disparos_falsos)} terminaram como falso alarme`;

    const taxa = a.disparos ? a.disparos_falsos / a.disparos : null;
    const taxaAnt = p.disparos ? p.disparos_falsos / p.disparos : null;
    $("k-falso").textContent = fmtPct(taxa);
    $("c-falso").innerHTML = taxa != null && taxaAnt != null ? chip(taxa - taxaAnt, { bomQuandoSobe: false, sufixo: " p.p." }) : chip(null);
    $("n-falso").textContent = "dos disparos de intrusão encerrados";

    $("k-tempo").textContent = fmtDur(a.tempo_medio_seg);
    $("c-tempo").innerHTML = chip(variacao(a.tempo_medio_seg, p.tempo_medio_seg), { bomQuandoSobe: false });
    $("n-tempo").textContent = `${fmtN(a.atendidos)} eventos atendidos e encerrados`;
    $("pill-tempo").textContent = `média geral ${fmtDur(a.tempo_medio_seg)}`;
  }

  function renderVolume(linhas, f) {
    const el = $("g-volume");
    const cats = ["alarme", "tecnico", "informativo"];
    legenda($("leg-categorias"), COR.categoria, ROTULO.categoria, cats);
    $("vol-total").textContent = fmtN(linhas.reduce((s, l) => s + l.n, 0));
    if (!linhas.length) return vazio(el);
    const dias = [];
    for (let d = f.inicio; d <= f.fim; d = addDias(d, 1)) dias.push(d);
    const porDia = {};
    linhas.forEach((l) => { (porDia[l.dia] ||= {})[l.categoria] = l.n; });
    const traces = cats.map((c) => ({
      type: "bar", name: ROTULO.categoria[c], x: dias, y: dias.map((d) => (porDia[d] || {})[c] || 0),
      marker: { color: COR.categoria[c], line: { color: COR.superficie, width: 1 } },
      hovertemplate: `%{x|%d/%m/%Y}<br>${ROTULO.categoria[c]}: <b>%{y}</b><extra></extra>`,
    }));
    const muitos = dias.length > 45;
    plot(el, traces, {
      barmode: "stack", bargap: muitos ? 0.15 : 0.35,
      xaxis: { type: "date", tickformat: "%d/%m", nticks: Math.min(dias.length, 12), ticklabelmode: "period" },
      yaxis: { rangemode: "tozero", tickformat: ",d", separatethousands: true },
    });
  }

  function renderCategorias(tipos) {
    const total = tipos.reduce((s, t) => s + t.n, 0);
    $("cat-total").textContent = total ? `${fmtN(total)} eventos` : "";
    const porCat = { alarme: 0, tecnico: 0, informativo: 0 };
    tipos.forEach((t) => { if (t.categoria in porCat) porCat[t.categoria] += t.n; });
    $("cat-barra").innerHTML = Object.entries(porCat).filter(([, n]) => n > 0)
      .map(([c, n]) => `<div class="h-full transition-all duration-700" style="width:${(n / total) * 100}%;background:${COR.categoria[c]}" title="${ROTULO.categoria[c]}: ${fmtN(n)}"></div>`).join("");
    $("cat-legenda").innerHTML = Object.entries(porCat)
      .map(([c, n]) => `<span class="flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full" style="background:${COR.categoria[c]}"></span>${ROTULO.categoria[c]} <span class="text-neutral-300 tabular-nums">${total ? fmtPct(n / total) : "–"}</span></span>`).join("");
    const max = tipos.length ? tipos[0].n : 1;
    $("lista-tipos").innerHTML = tipos.slice(0, 6).map((t) => `
      <div class="flex items-center gap-3 text-xs group/l">
        <span class="w-1.5 h-1.5 rounded-full flex-none" style="background:${COR.categoria[t.categoria] || COR.texto}"></span>
        <span class="text-neutral-400 group-hover/l:text-white transition-colors truncate flex-1" title="${esc(t.codigo)}">${esc(t.descricao || t.codigo)}</span>
        <span class="w-16 h-1 rounded-full bg-white/5 overflow-hidden flex-none"><span class="block h-full rounded-full transition-all duration-700" style="width:${(t.n / max) * 100}%;background:${COR.categoria[t.categoria] || COR.texto}"></span></span>
        <span class="text-white tabular-nums w-12 text-right">${fmtN(t.n)}</span>
      </div>`).join("") || `<div class="vazio">Sem dados</div>`;
  }

  // 02 ---------------------------------------------------------------------
  const COR_PRIORIDADE_TILE = {
    critica: "bg-rose-500/10 border-rose-500/20 text-rose-400", alta: "bg-amber-500/10 border-amber-500/25 text-amber-400",
    media: "bg-yellow-500/10 border-yellow-500/20 text-yellow-300", baixa: "bg-emerald-500/10 border-emerald-500/20 text-emerald-400",
  };
  function renderAgora(abertos, situacao) {
    const n = abertos.length;
    contar($("k-abertos"), n, 900);
    $("nav-abertos").textContent = fmtN(n);
    $("nav-abertos").className = "text-[10px] font-bold px-1.5 py-0.5 rounded-md border tabular-nums leading-none transition-colors " +
      (n ? "bg-amber-500/10 border-amber-500/25 text-amber-400" : "bg-white/5 border-white/10 text-neutral-400");
    $("k-aguardando").textContent = fmtN(abertos.filter((e) => e.status === "aberto").length);
    $("k-em-atendimento").textContent = fmtN(abertos.filter((e) => e.status === "em_atendimento").length);
    $("k-mais-antigo").textContent = n ? fmtTempoAtras(Math.max(...abertos.map((e) => e.minutos))) : "–";
    const pill = $("agora-pill"), txt = $("agora-texto");
    pill.className = "flex items-center gap-2 px-3 py-1.5 rounded-full backdrop-blur-sm w-fit border transition-colors " +
      (n ? "bg-amber-500/10 border-amber-500/25" : "bg-emerald-500/10 border-emerald-500/20");
    txt.className = "text-xs font-medium " + (n ? "text-amber-400" : "text-emerald-400");
    txt.textContent = n ? `${n} na fila` : "Fila vazia";

    $("lista-abertos").innerHTML = n ? abertos.map((e) => `
      <div class="flex items-center justify-between p-4 hover:bg-white/[0.02] transition-colors border-b border-white/5 last:border-0 gap-4 group">
        <div class="flex items-center gap-3 min-w-0">
          <div class="w-8 h-8 rounded-lg border flex items-center justify-center flex-none transition-colors ${COR_PRIORIDADE_TILE[e.prioridade] || "bg-white/5 border-white/10 text-white"}" title="Prioridade ${ROTULO.prioridade[e.prioridade] || e.prioridade}">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>
          </div>
          <div class="flex flex-col min-w-0">
            <span class="text-xs font-medium text-white truncate">${esc(e.descricao || e.codigo_evento)} <span class="text-neutral-500 font-normal">· ${esc(e.cliente || e.cliente_id)}</span></span>
            <span class="text-[10px] text-neutral-500">${esc(e.cidade || "cidade desconhecida")} · ${ROTULO.tipo[e.tipo_cliente] || "–"} · ${e.zona ? "zona " + e.zona + " · " : ""}${fmtData(e.data_hora)} ${fmtHora(e.data_hora)}${e.operador ? " · " + esc(e.operador) : ""}</span>
          </div>
        </div>
        <div class="flex items-center gap-3 flex-none">
          <span class="chip ${e.status === "aberto" ? "chip-ruim" : "chip-aviso"}">${ROTULO.status[e.status]}</span>
          <span class="text-xs text-neutral-400 tabular-nums w-16 text-right">${fmtTempoAtras(e.minutos)}</span>
        </div>
      </div>`).join("")
      : `<div class="vazio flex items-center justify-center gap-2"><span class="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>Nenhum evento aberto ou em atendimento neste momento</div>`;

    renderSituacao(situacao, n);
  }
  function renderSituacao(s, fila = 0) {
    const titulo = $("status-titulo"), sub = $("status-sub"), dot = $("status-dot"), dot2 = $("status-dot-2"),
      ping = $("status-ping"), pill = $("status-pill"), pillTxt = $("status-pill-texto"), heroPill = $("hero-pill"),
      sino = $("sino"), sinoDot = $("sino-dot");
    let cor = "emerald", texto = "carregando…", tituloTxt = "Dados da captura", subTxt = "", pulsa = true;
    if (!s || !s.existe) {
      cor = "rose"; texto = "sem captura"; tituloTxt = "Sem captura"; subTxt = "rode python capturar.py"; pulsa = false;
    } else {
      const velho = s.minutos_atras == null || s.minutos_atras > 15, erro = s.status === "erro";
      cor = erro ? "rose" : velho ? "yellow" : "emerald"; pulsa = !velho && !erro;
      texto = s.minutos_atras == null ? "captura em andamento" : `dados ${fmtTempoAtras(s.minutos_atras)}`;
      tituloTxt = erro ? "Última captura falhou" : "Dados da captura";
      subTxt = s.minutos_atras == null ? `execução ${s.execucao} em andamento` : `${s.modo} · ${fmtTempoAtras(s.minutos_atras)}`;
      if (heroPill && s.ultimo_evento) heroPill.textContent = `último evento às ${fmtHora(s.ultimo_evento)} de ${fmtDataCurta(s.ultimo_evento)}`;
    }
    const tom = { emerald: ["bg-emerald-500", "bg-emerald-400", "bg-emerald-500/10 border-emerald-500/20", "text-emerald-400"],
                  yellow: ["bg-yellow-400", "bg-yellow-300", "bg-yellow-500/10 border-yellow-500/25", "text-yellow-300"],
                  rose: ["bg-rose-500", "bg-rose-400", "bg-rose-500/10 border-rose-500/20", "text-rose-400"] }[cor];
    titulo.textContent = tituloTxt; sub.textContent = subTxt;
    dot.className = "relative inline-flex rounded-full h-2 w-2 " + tom[0];
    dot2.className = "relative inline-flex rounded-full h-2 w-2 " + tom[0];
    ping.className = "animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 " + (pulsa ? tom[1] : "hidden");
    pill.className = "hidden md:flex items-center gap-2 px-3 py-1.5 rounded-full border backdrop-blur-sm transition-colors " + tom[2];
    pillTxt.className = "text-xs font-medium " + tom[3];
    pillTxt.textContent = texto;
    const avisos = [];
    if (fila) avisos.push(`${fila} na fila`);
    if (cor !== "emerald") avisos.push(texto);
    sinoDot.classList.toggle("hidden", !avisos.length);
    sino.title = avisos.length ? avisos.join(" · ") : "Sem avisos";
  }

  // 03 ---------------------------------------------------------------------
  function barrasHorizontais(el, rotulos, valores, { cores, hover, extra = {}, anotacoes } = {}) {
    if (!valores.length) return vazio(el);
    return plot(el, [{
      type: "bar", orientation: "h", x: valores, y: rotulos,
      marker: { color: cores || COR.serie, line: { color: COR.superficie, width: 1 } },
      text: valores.map(anotacoes || ((v) => fmtN(v))), textposition: "outside", cliponaxis: false,
      textfont: { family: FONTE, size: 10, color: "#cbd5e1" }, hovertemplate: hover || "%{y}: <b>%{x}</b><extra></extra>",
      ...extra,
    }], {
      margin: { l: 8, r: 56, t: 4, b: 24 }, bargap: 0.4,
      xaxis: { gridcolor: COR.grade, showticklabels: false, rangemode: "tozero" },
      yaxis: { gridcolor: "rgba(0,0,0,0)", autorange: "reversed", tickfont: { size: 11, color: "#a3a3a3" }, ticksuffix: "  " },
    });
  }
  function renderPrioridade(linhas) {
    barrasHorizontais($("g-prioridade"),
      linhas.map((l) => ROTULO.prioridade[l.prioridade] || l.prioridade),
      linhas.map((l) => Math.round(l.media_seg)),
      { anotacoes: (v) => fmtDur(v), hover: linhas.map((l) => `${ROTULO.prioridade[l.prioridade]}<br>média <b>${fmtDur(l.media_seg)}</b> em ${fmtN(l.atendimentos)} atendimentos<br>máximo ${fmtDur(l.maximo_seg)}<extra></extra>`) });
  }
  function renderOperador(linhas) {
    const el = $("g-operador");
    if (!linhas.length) return vazio(el);
    const nomes = linhas.map((l) => l.operador);
    const razao = linhas.map((l) => l.media_seg / l.esperado_seg);
    const cores = razao.map((r) => (r >= 1.3 ? COR.destaque : COR.serie));
    plot(el, [
      { type: "bar", orientation: "h", x: linhas.map((l) => Math.round(l.media_seg)), y: nomes,
        marker: { color: cores, line: { color: COR.superficie, width: 1 } },
        text: linhas.map((l) => fmtDur(l.media_seg)), textposition: "outside", cliponaxis: false, textfont: { family: FONTE, size: 10, color: "#cbd5e1" },
        hovertemplate: linhas.map((l, i) => `<b>${esc(l.operador)}</b><br>média real ${fmtDur(l.media_seg)} · esperado ${fmtDur(l.esperado_seg)} (${razao[i].toFixed(2)}×)<br>${fmtN(l.atendimentos)} atendimentos · ${fmtPct(l.fracao_noite)} à noite<extra></extra>`) },
      { type: "scatter", mode: "markers", x: linhas.map((l) => Math.round(l.esperado_seg)), y: nomes,
        marker: { symbol: "line-ns", size: 18, line: { color: COR.esperado, width: 2 }, opacity: 0.8 },
        hovertemplate: "esperado: <b>%{x} s</b><extra></extra>" },
    ], {
      margin: { l: 8, r: 64, t: 4, b: 24 }, bargap: 0.45,
      xaxis: { gridcolor: COR.grade, showticklabels: false, rangemode: "tozero" },
      yaxis: { gridcolor: "rgba(0,0,0,0)", autorange: "reversed", tickfont: { size: 11, color: "#a3a3a3" }, ticksuffix: "  " },
    });
  }

  const COR_TURNO = { dia: "#3b82f6", noite: "#059669" };
  function renderTurnos(linhas) {
    const el = $("carga-turno");
    const total = linhas.reduce((s, l) => s + l.atendimentos, 0);
    const disparos = linhas.reduce((s, l) => s + l.disparos, 0);
    if (!total) { el.innerHTML = `<div class="vazio">Sem atendimentos no período</div>`; return; }
    el.innerHTML = linhas.map((l) => `
      <div>
        <div class="flex items-end justify-between mb-2">
          <div class="flex items-center gap-2"><span class="w-1.5 h-1.5 rounded-full" style="background:${COR_TURNO[l.turno]}"></span><span class="text-xs text-neutral-300">${ROTULO.turno[l.turno] || l.turno}</span></div>
          <span class="text-2xl font-semibold text-white tracking-tight tabular-nums">${fmtN(l.atendimentos)} <span class="text-xs text-neutral-500 font-normal">${fmtPct(l.atendimentos / total)}</span></span>
        </div>
        <div class="flex h-1.5 w-full rounded-full overflow-hidden bg-white/5"><div class="h-full transition-all duration-700" style="width:${(l.atendimentos / total) * 100}%;background:${COR_TURNO[l.turno]}"></div></div>
        <div class="flex justify-between mt-2 text-[10px] text-neutral-500">
          <span>${fmtN(l.disparos)} disparos${disparos ? ` (${fmtPct(l.disparos / disparos)})` : ""}</span>
          <span>média ${fmtDur(l.media_seg)} · ${l.operadores} operador${l.operadores === 1 ? "" : "es"}</span>
        </div>
      </div>`).join("");
  }
  function renderDesfechos(linhas) {
    const el = $("lista-desfechos"), txt = $("txt-desfechos");
    if (!linhas.length) { el.innerHTML = `<div class="vazio">Sem atendimentos no período</div>`; txt.textContent = ""; return; }
    const horas = linhas.reduce((s, l) => s + l.horas, 0), max = linhas[0].horas;
    const falso = linhas.find((l) => l.resultado === "falso_alarme");
    const lento = [...linhas].sort((a, b) => b.media_seg - a.media_seg)[0];
    txt.textContent = `${horas.toLocaleString("pt-BR", { maximumFractionDigits: 0 })} h de atendimento no período`
      + (falso ? `, ${fmtPct(falso.horas / horas)} delas em alarmes que eram falsos` : "")
      + `. O desfecho mais demorado é "${ROTULO.resultado[lento.resultado] || lento.resultado}": ${fmtDur(lento.media_seg)} por caso.`;
    el.innerHTML = linhas.map((l) => `
      <div class="flex items-center gap-3 text-xs">
        <span class="w-36 text-neutral-300 truncate">${ROTULO.resultado[l.resultado] || l.resultado}</span>
        <span class="flex-1 h-1.5 rounded-full bg-white/5 overflow-hidden"><span class="block h-full rounded-full transition-all duration-700" style="width:${(l.horas / max) * 100}%;background:${l.resultado === "falso_alarme" ? COR.destaque : COR.serie}"></span></span>
        <span class="w-14 text-right text-white tabular-nums">${l.horas.toLocaleString("pt-BR", { maximumFractionDigits: 1 })} h</span>
        <span class="w-28 text-right text-neutral-500 tabular-nums">${fmtN(l.n)} · ${fmtDur(l.media_seg)}</span>
      </div>`).join("");
  }

  // 04 ---------------------------------------------------------------------
  function renderDisparos(linhas) {
    const t = $("t-disparos");
    if (!linhas.length) { t.innerHTML = `<tr><td class="vazio">Nenhum disparo no período</td></tr>`; return; }
    t.innerHTML = `<thead><tr><th>#</th><th>Cliente</th><th class="num">Disparos</th><th>Falso alarme</th><th class="num">Viatura / polícia</th></tr></thead><tbody>` +
      linhas.map((l, i) => {
        const taxa = l.disparos ? l.falsos / l.disparos : 0;
        const suspeito = l.disparos >= 10 && taxa >= 0.9;
        return `<tr>
          <td class="text-neutral-600 tabular-nums">${i + 1}</td>
          <td class="nome"><span class="principal">${esc(l.nome)}</span>${suspeito ? ` <span class="chip chip-ruim ml-1" title="Quase todo disparo é falso: provável sensor com defeito">sensor?</span>` : ""}<span class="sub">${esc(l.cidade)} · ${ROTULO.tipo[l.tipo] || l.tipo} · ${esc(l.plano)} · ${l.dias_com_disparo} dias com disparo</span></td>
          <td class="num principal">${fmtN(l.disparos)}</td>
          <td><div class="flex items-center gap-3"><span class="barra" title="${fmtN(l.falsos)} de ${fmtN(l.disparos)}"><span style="width:${taxa * 100}%;background:${taxa >= 0.9 ? COR.destaque : COR.serie}"></span></span><span class="tabular-nums text-neutral-300 w-10 text-right">${fmtPct(taxa)}</span></div></td>
          <td class="num">${fmtN(l.acionamentos)}</td>
        </tr>`;
      }).join("") + "</tbody>";
  }
  function renderTecnicos(linhas) {
    const t = $("t-tecnicos");
    legenda($("leg-tecnicos"), COR.tecnico, ROTULO.tecnico, ["comunicacao", "energia", "bateria"]);
    if (!linhas.length) { t.innerHTML = `<tr><td class="vazio">Nenhum problema técnico no período</td></tr>`; return; }
    const max = linhas[0].total;
    t.innerHTML = `<thead><tr><th>#</th><th>Cliente</th><th>Composição</th><th class="num">Total</th><th class="num">Dias</th></tr></thead><tbody>` +
      linhas.map((l, i) => `<tr>
        <td class="text-neutral-600 tabular-nums">${i + 1}</td>
        <td class="nome"><span class="principal">${esc(l.nome)}</span><span class="sub">${esc(l.cidade)} · ${ROTULO.tipo[l.tipo] || l.tipo}</span></td>
        <td><span class="barra" style="width:${Math.max(30, (l.total / max) * 100)}%" title="comunicação ${l.comunicacao} · energia ${l.energia} · bateria ${l.bateria}">
          ${["comunicacao", "energia", "bateria"].filter((k) => l[k] > 0).map((k) => `<span style="width:${(l[k] / l.total) * 100}%;background:${COR.tecnico[k]}"></span>`).join("")}</span>
          <span class="sub">${l.comunicacao} com · ${l.energia} ene · ${l.bateria} bat</span></td>
        <td class="num principal">${fmtN(l.total)}</td>
        <td class="num">${fmtN(l.dias_com_problema)}</td>
      </tr>`).join("") + "</tbody>";
  }

  // 05 ---------------------------------------------------------------------
  function renderHora(linhas) {
    const el = $("g-hora");
    if (!linhas.length) { vazio(el); $("txt-hora").textContent = "Sem disparos no período"; return; }
    const porHora = Array(24).fill(0);
    linhas.forEach((l) => { porHora[l.hora] = l.n; });
    const total = porHora.reduce((a, b) => a + b, 0);
    const madrugada = [22, 23, 0, 1, 2, 3, 4, 5].reduce((s, h) => s + porHora[h], 0);
    $("txt-hora").textContent = `${fmtPct(madrugada / total)} dos disparos acontecem entre 22h e 6h, quando os imóveis estão fechados.`;
    plot(el, [{
      type: "bar", x: porHora.map((_, h) => h), y: porHora,
      marker: { color: porHora.map((_, h) => (h >= 22 || h < 6 ? COR.serie : "rgba(16,185,129,0.35)")), line: { color: COR.superficie, width: 1 } },
      hovertemplate: "%{x}h–%{x}h59: <b>%{y}</b> disparos<extra></extra>",
    }], {
      bargap: 0.25, xaxis: { tickvals: [0, 6, 12, 18, 23], ticktext: ["0h", "6h", "12h", "18h", "23h"] },
      yaxis: { rangemode: "tozero" },
    });
  }
  function renderEnergia(linhas) {
    const el = $("g-energia");
    if (!linhas.length) { vazio(el); $("txt-energia").textContent = "Sem faltas de energia no período"; return; }
    const porDia = {};
    linhas.forEach((l) => { (porDia[l.dia] ||= { total: 0, cidades: [] }); porDia[l.dia].total += l.n; porDia[l.dia].cidades.push(`${l.cidade} ${l.n}`); });
    const dias = Object.keys(porDia).sort();
    const totais = dias.map((d) => porDia[d].total);
    const limiar = Math.max(4, 3 * mediana(totais));
    const picos = dias.filter((d) => porDia[d].total >= limiar);
    $("txt-energia").textContent = picos.length
      ? `${picos.length} ${picos.length === 1 ? "dia concentra" : "dias concentram"} ${fmtPct(picos.reduce((s, d) => s + porDia[d].total, 0) / totais.reduce((a, b) => a + b, 0))} das quedas: ${picos.map((d) => `${fmtDataCurta(d)} (${porDia[d].cidades.join(", ")})`).join("; ")}. Padrão de temporal regional, não de equipamento.`
      : "Quedas de energia espalhadas, sem dia atípico.";
    plot(el, [{
      type: "bar", x: dias, y: totais,
      marker: { color: dias.map((d) => (porDia[d].total >= limiar ? COR.pico : "#059669")), line: { color: COR.superficie, width: 1 } },
      customdata: dias.map((d) => porDia[d].cidades.join("<br>")),
      hovertemplate: "%{x|%d/%m/%Y}: <b>%{y}</b> faltas de energia<br><span style='color:#a3a3a3'>%{customdata}</span><extra></extra>",
    }], {
      bargap: 0.3, xaxis: { type: "date", tickformat: "%d/%m" }, yaxis: { rangemode: "tozero" },
    });
  }
  function renderTestes(linhas) {
    const t = $("t-testes");
    const relevantes = linhas.filter((l) => l.dias_sem_teste > 0);
    if (!relevantes.length) { t.innerHTML = `<tr><td class="vazio">Todos os clientes enviaram o teste diário em todos os dias ativos</td></tr>`; $("insight-testes").innerHTML = ""; return; }
    t.innerHTML = `<thead><tr><th>Cliente</th><th>Dias sem teste</th><th class="num quebra">Dias<br>ativos</th><th class="num quebra">Falhas de<br>comunicação</th></tr></thead><tbody>` +
      relevantes.map((l) => {
        const frac = l.dias_sem_teste / l.dias_ativos;
        return `<tr>
          <td class="nome"><span class="principal">${esc(l.nome)}</span><span class="sub">${esc(l.cidade)} · ${ROTULO.tipo[l.tipo] || l.tipo}</span></td>
          <td><div class="flex items-center gap-3"><span class="barra"><span style="width:${frac * 100}%;background:${frac >= 0.2 ? COR.destaque : COR.serie}"></span></span><span class="tabular-nums text-white w-20 text-right">${l.dias_sem_teste} <span class="text-neutral-500">(${fmtPct(frac)})</span></span></div></td>
          <td class="num">${fmtN(l.dias_ativos)}</td>
          <td class="num ${l.falhas_comunicacao >= 10 ? "text-amber-400" : ""}">${fmtN(l.falhas_comunicacao)}</td>
        </tr>`;
      }).join("") + "</tbody>";
    const cronicos = relevantes.filter((l) => l.dias_sem_teste / l.dias_ativos >= 0.2);
    $("insight-testes").innerHTML = cronicos.length
      ? insight(`${cronicos.length} ${cronicos.length === 1 ? "cliente passa" : "clientes passam"} mais de 20% dos dias sem teste`,
        `${cronicos.map((l) => `<b>${esc(l.nome)}</b>`).join(", ")} ${cronicos.length === 1 ? "não envia" : "não enviam"} o teste periódico em boa parte dos dias e ${cronicos.length === 1 ? "concentra" : "concentram"} <b>${fmtN(cronicos.reduce((s, l) => s + l.falhas_comunicacao, 0))}</b> falhas de comunicação no período. ` +
        `Dia sem teste é dia em que a central não sabe se o painel está protegendo o imóvel. Vale agendar visita técnica antes de um disparo real passar em branco.`, true)
      : insight("Teste periódico em dia", "Nenhum cliente passa mais de 20% dos dias sem o teste. As ausências pontuais acima são compatíveis com falhas isoladas.");
  }

  // 06 ---------------------------------------------------------------------
  function renderQualidade(q) {
    const t = q.totais;
    contar($("q-eventos"), t.eventos_com_correcao);
    $("q-eventos-chip").innerHTML = `<span class="chip chip-neutro">${fmtPct(t.eventos_com_correcao / t.eventos, 1)}</span>`;
    $("q-eventos-nota").textContent = `de ${fmtN(t.eventos)} eventos no banco`;
    contar($("q-clientes"), t.clientes_com_correcao);
    $("q-clientes-chip").innerHTML = `<span class="chip chip-neutro">${fmtPct(t.clientes_com_correcao / t.clientes)}</span>`;
    $("q-clientes-nota").textContent = `de ${fmtN(t.clientes)} clientes (cidade ou nome)`;
    contar($("q-sem-cliente"), t.sem_cliente);
    contar($("q-rejeitados"), t.rejeitados);

    const prob = [...q.por_problema].sort((a, b) => a.n - b.n);
    const p = barrasHorizontais($("g-problemas"),
      prob.map((x) => ROTULO.problema[x.problema] || x.problema), prob.map((x) => x.n),
      { hover: prob.map((x) => `<b>${ROTULO.problema[x.problema] || x.problema}</b> · campo ${x.campo}<br>${fmtN(x.n)} ${x.entidade === "cliente" ? "clientes" : "eventos"}` + (q.exemplos[x.problema] != null ? `<br>ex.: <span style="color:#a3a3a3">${esc(q.exemplos[x.problema])}</span>` : "") + "<extra></extra>") });
    if (p) p.then(() => Plotly.relayout($("g-problemas"), { "yaxis.autorange": true, "yaxis.tickfont.size": 10 }));

    const ex = $("t-execucoes");
    ex.classList.add("compacta");
    ex.innerHTML = `<thead><tr><th>#</th><th>Início</th><th>Modo</th><th>Status</th><th class="num">Lidos</th><th class="num">Novos</th><th class="num quebra">Atuali-<br>zados</th><th class="num quebra">Repe-<br>tidos</th><th class="num quebra">Retenta-<br>tivas</th></tr></thead><tbody>` +
      q.execucoes.map((e) => `<tr>
        <td class="text-neutral-600 tabular-nums">${e.id}</td>
        <td class="tabular-nums">${fmtData(e.inicio)} ${e.inicio.slice(11, 16)} <span class="text-neutral-600">UTC</span></td>
        <td>${e.modo}</td>
        <td><span class="chip ${e.status === "ok" ? "chip-bom" : e.status === "erro" ? "chip-ruim" : "chip-aviso"}" title="${esc(e.erro || "")}">${e.status}</span></td>
        <td class="num">${fmtN(e.registros_lidos)}</td><td class="num principal">${fmtN(e.novos)}</td><td class="num">${fmtN(e.atualizados)}</td>
        <td class="num" title="mesmo id, mesmo conteúdo: duplicata da API ou fronteira do cursor">${fmtN(e.inalterados)}</td>
        <td class="num ${e.retentativas ? "text-amber-400" : ""}">${fmtN(e.retentativas)}</td>
      </tr>`).join("") + "</tbody>";
  }

  // ------------------------------------------------------------------ "agora" ao vivo
  async function atualizarAgora() {
    try {
      const r = await fetch("/api/agora?" + query(false));
      const d = await r.json();
      renderAgora(d.abertos, d.situacao);
    } catch (e) { /* tenta de novo no próximo minuto */ }
  }

  // ------------------------------------------------------------------ navegação (pílula + sidebar)
  function ligarNavegacao() {
    const links = [...document.querySelectorAll(".nav-link, .nav-item")];
    const secoes = [...document.querySelectorAll("section[id][data-titulo]")];
    const obs = new IntersectionObserver((entries) => {
      entries.forEach((en) => {
        if (!en.isIntersecting) return;
        const id = en.target.id;
        links.forEach((a) => a.classList.toggle("ativo", a.getAttribute("href") === "#" + id));
        if (id === "visao-geral" || id === "agora") $("breadcrumb").textContent = en.target.dataset.titulo;
      });
    }, { rootMargin: "-25% 0px -60% 0px" });
    secoes.forEach((s) => obs.observe(s));
  }

  // ------------------------------------------------------------------ início
  lerURL();
  ligarFiltros();
  ligarNavegacao();
  renderSituacao(window.PAINEL.situacao);
  aplicar();
  setInterval(atualizarAgora, 60000);
})();
