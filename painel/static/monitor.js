/* Modo monitoramento: lê /api/monitor a cada 2 minutos e mostra a fila em tela cheia. */
(function () {
  "use strict";
  const INTERVALO = 120;  // segundos entre atualizações

  const $ = (id) => document.getElementById(id);
  const fmtN = (n) => (n == null ? "–" : Number(n).toLocaleString("pt-BR"));
  const fmtPct = (x) => (x == null || isNaN(x) ? "–" : Math.round(x * 100) + "%");
  const fmtDur = (seg) => {
    if (seg == null || isNaN(seg)) return "–";
    seg = Math.round(seg);
    if (seg < 60) return `${seg} s`;
    const m = Math.floor(seg / 60), s = seg % 60;
    return m < 60 ? `${m} min${s ? " " + String(s).padStart(2, "0") + " s" : ""}` : `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")} min`;
  };
  const fmtMin = (min) => (min < 60 ? `${min} min` : min < 1440 ? `${Math.floor(min / 60)} h ${String(min % 60).padStart(2, "0")}` : `${Math.floor(min / 1440)} d`);
  const fmtHora = (dh) => dh.slice(11, 16);
  const fmtData = (iso) => { const [a, m, d] = iso.slice(0, 10).split("-"); return `${d}/${m}/${a}`; };
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const ROT = {
    prioridade: { critica: "Crítica", alta: "Alta", media: "Média", baixa: "Baixa" },
    status: { aberto: "Aguardando", em_atendimento: "Em atendimento" },
    tipo: { residencial: "Residencial", comercial: "Comercial", agencia_bancaria: "Agência bancária", industrial: "Industrial" },
    resultado: { falso_alarme: "Falso alarme", cliente_contatado: "Cliente contatado", tecnico_agendado: "Técnico agendado", sem_contato: "Sem contato", viatura_enviada: "Viatura enviada", policia_acionada: "Polícia acionada", bombeiros_acionados: "Bombeiros acionados" },
  };
  // Tempo que a central considera aceitável até fechar, por prioridade (em minutos).
  const LIMITE_MIN = { critica: 3, alta: 8, media: 20, baixa: 45 };
  const ICONE = `<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>`;

  const q = new URLSearchParams(location.search);
  const filtro = { cidade: q.get("cidade") || "", tipo: q.get("tipo") || "" };
  const query = () => { const p = new URLSearchParams(); if (filtro.cidade) p.set("cidade", filtro.cidade); if (filtro.tipo) p.set("tipo", filtro.tipo); return p.toString(); };
  $("m-filtro").textContent = [filtro.cidade, ROT.tipo[filtro.tipo]].filter(Boolean).join(" · ");

  let idsAnteriores = new Set();

  function renderFila(abertos) {
    const el = $("m-fila"), n = abertos.length;
    $("m-total").textContent = fmtN(n);
    $("m-aguardando").textContent = fmtN(abertos.filter((e) => e.status === "aberto").length);
    $("m-atendendo").textContent = fmtN(abertos.filter((e) => e.status === "em_atendimento").length);
    $("m-criticos").textContent = fmtN(abertos.filter((e) => e.prioridade === "critica" || e.prioridade === "alta").length);
    $("m-antigo").textContent = n ? fmtMin(Math.max(...abertos.map((e) => e.minutos))) : "–";
    const pill = $("m-fila-pill"), txt = $("m-fila-texto");
    pill.className = "flex items-center gap-2 px-4 py-2 rounded-full border transition-colors " + (n ? "bg-amber-500/10 border-amber-500/25" : "bg-emerald-500/10 border-emerald-500/20");
    txt.className = "text-sm font-medium " + (n ? "text-amber-400" : "text-emerald-400");
    txt.textContent = n ? `${n} na fila` : "Fila vazia";
    if (!n) {
      el.innerHTML = `<div class="fila-vazia"><div class="anel"><svg xmlns="http://www.w3.org/2000/svg" width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/></svg></div><p class="text-lg text-white font-light">Nenhum evento aguardando</p><p class="text-sm">Tudo que chegou à central foi atendido e encerrado.</p></div>`;
      idsAnteriores = new Set(); return;
    }
    const ordem = { critica: 0, alta: 1, media: 2, baixa: 3 };
    const lista = [...abertos].sort((a, b) => (ordem[a.prioridade] ?? 9) - (ordem[b.prioridade] ?? 9) || b.minutos - a.minutos);
    el.innerHTML = lista.map((e) => {
      const atrasado = e.minutos > (LIMITE_MIN[e.prioridade] ?? 60);
      return `<div class="fila-item ${idsAnteriores.size && !idsAnteriores.has(e.id) ? "nova" : ""}">
        <div class="fila-tile ${e.prioridade || ""}" title="Prioridade ${ROT.prioridade[e.prioridade] || e.prioridade}">${ICONE}</div>
        <div class="min-w-0">
          <div class="fila-titulo">${esc(e.descricao || e.codigo_evento)} <span class="text-neutral-500 font-normal">· ${esc(e.cliente || e.cliente_id)}</span></div>
          <div class="fila-sub">${esc(e.cidade || "cidade desconhecida")} · ${ROT.tipo[e.tipo_cliente] || "–"}${e.zona ? " · zona " + e.zona : ""} · ${fmtHora(e.data_hora)}${e.operador ? " · " + esc(e.operador) : ""}</div>
        </div>
        <span class="chip chip-g ${e.status === "aberto" ? "chip-ruim" : "chip-aviso"}">${ROT.status[e.status] || e.status}</span>
        <div class="fila-tempo ${atrasado ? "atrasado" : ""}">${fmtMin(e.minutos)}<small>${atrasado ? "acima do limite" : "na fila"}</small></div>
      </div>`;
    }).join("");
    idsAnteriores = new Set(abertos.map((e) => e.id));
  }

  function renderHoje(h) {
    $("m-hoje-data").textContent = new Date().toLocaleDateString("pt-BR", { weekday: "long", day: "2-digit", month: "long" });
    $("h-eventos").textContent = fmtN(h.eventos);
    $("h-disparos").textContent = fmtN(h.disparos);
    $("h-falsos").textContent = h.disparos ? fmtPct(h.disparos_falsos / h.disparos) : "–";
    $("h-tempo").textContent = fmtDur(h.tempo_medio_seg);
  }

  function render24h(linhas) {
    const el = $("m-24h");
    const agora = new Date(); agora.setMinutes(0, 0, 0);
    const horas = [];
    for (let i = 23; i >= 0; i--) { const d = new Date(agora.getTime() - i * 3600000); horas.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}`); }
    const por = Object.fromEntries(linhas.map((l) => [l.hora, l]));
    const max = Math.max(1, ...horas.map((h) => (por[h] || {}).n || 0));
    el.innerHTML = horas.map((h, i) => {
      const l = por[h] || { n: 0, alarmes: 0 };
      return `<div class="b24 ${i === 23 ? "atual" : ""}" title="${h.slice(11)}h: ${l.n} eventos, ${l.alarmes} alarmes"><span style="height:${Math.max(l.n ? 6 : 0, (l.n / max) * 100)}%"></span>${l.alarmes ? `<span class="alarme" style="height:${Math.max(6, (l.alarmes / max) * 100)}%"></span>` : ""}</div>`;
    }).join("");
    $("m-24h-ini").textContent = horas[0].slice(11) + "h";
  }

  function renderEncerrados(linhas) {
    $("m-encerrados").innerHTML = linhas.length ? linhas.map((e) => `
      <div class="enc-item">
        <div class="min-w-0">
          <div class="text-sm text-white truncate">${esc(e.descricao)} <span class="text-neutral-500">· ${esc(e.cliente || "cliente desconhecido")}</span></div>
          <div class="text-[11px] text-neutral-500 truncate">${fmtData(e.data_hora)} ${fmtHora(e.data_hora)} · ${esc(e.cidade || "–")}${e.operador ? " · " + esc(e.operador) : ""}</div>
        </div>
        <div class="text-right flex-none">
          <div class="text-xs font-medium ${e.resultado === "falso_alarme" ? "text-rose-400" : "text-emerald-400"}">${ROT.resultado[e.resultado] || e.resultado || "–"}</div>
          <div class="text-[11px] text-neutral-500 tabular-nums">${fmtDur(e.tempo_atendimento_seg)}</div>
        </div>
      </div>`).join("") : `<div class="vazio">Nenhum encerramento registrado</div>`;
  }

  function renderStatus(s) {
    const txt = $("m-status-texto"), dot = $("m-dot"), ping = $("m-ping"), pill = $("m-status");
    let cor = "emerald", texto = "dados em dia";
    if (!s || !s.existe) { cor = "rose"; texto = "sem captura"; }
    else if (s.status === "erro") { cor = "rose"; texto = "última captura falhou"; }
    else if (s.minutos_atras == null) { texto = "captura em andamento"; }
    else if (s.minutos_atras > 15) { cor = "yellow"; texto = `dados de ${fmtMin(s.minutos_atras)} atrás`; }
    else texto = `dados há ${s.minutos_atras} min`;
    const tom = { emerald: ["bg-emerald-500", "bg-emerald-400", "bg-emerald-500/10 border-emerald-500/20", "text-emerald-400"],
                  yellow: ["bg-yellow-400", "hidden", "bg-yellow-500/10 border-yellow-500/25", "text-yellow-300"],
                  rose: ["bg-rose-500", "bg-rose-400", "bg-rose-500/10 border-rose-500/20", "text-rose-400"] }[cor];
    dot.className = "relative inline-flex rounded-full h-2 w-2 " + tom[0];
    ping.className = "animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 " + tom[1];
    pill.className = "flex items-center gap-2 px-3 py-1.5 rounded-full border transition-colors " + tom[2];
    txt.className = "text-xs font-medium " + tom[3];
    txt.textContent = texto;
  }

  let restante = INTERVALO;
  async function atualizar() {
    try {
      const r = await fetch("/api/monitor?" + query(), { cache: "no-store" });
      const d = await r.json();
      renderFila(d.abertos); renderHoje(d.hoje); render24h(d.ultimas_24h); renderEncerrados(d.encerrados); renderStatus(d.situacao);
    } catch (e) {
      renderStatus({ existe: true, status: "erro" });
    } finally {
      restante = INTERVALO;
    }
  }

  // relógio e contagem regressiva, a cada segundo; dados a cada 2 minutos
  setInterval(() => {
    const t = new Date();
    $("m-relogio").textContent = `${String(t.getHours()).padStart(2, "0")}:${String(t.getMinutes()).padStart(2, "0")}:${String(t.getSeconds()).padStart(2, "0")}`;
    restante -= 1;
    $("m-contagem").textContent = `${Math.floor(Math.max(0, restante) / 60)}:${String(Math.max(0, restante) % 60).padStart(2, "0")}`;
    if (restante <= 0) atualizar();
  }, 1000);

  $("m-tela").addEventListener("click", () => {
    if (document.fullscreenElement) document.exitFullscreen(); else document.documentElement.requestFullscreen().catch(() => {});
  });
  document.addEventListener("keydown", (e) => { if (e.key === "r" || e.key === "R") atualizar(); });

  atualizar();
})();
