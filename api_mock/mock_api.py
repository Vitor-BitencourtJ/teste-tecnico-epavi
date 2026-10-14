#!/usr/bin/env python3
"""
API mock - Central de Monitoramento (Teste Tecnico Epavi)
==========================================================

Simula a API de eventos de uma central de monitoramento de alarmes.
Usa APENAS a biblioteca padrao do Python (3.8+). Nada para instalar.

    python mock_api.py                 # sobe em http://localhost:8000
    python mock_api.py --porta 9000

Leia o README_API.md para a documentacao dos endpoints.
Os dados sao 100% ficticios.
"""
import argparse
import json
import random
import threading
import time
from collections import deque
from datetime import date, datetime, time as dtime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

API_KEY = "epavi-teste-2026"
SEED = 2026
TZ_BR = timezone(timedelta(hours=-3))
DIAS_HISTORICO = 90
LIMITE_REQ_POR_SEG = 5
POR_PAGINA_PADRAO = 50
POR_PAGINA_MAX = 200

# ---------------------------------------------------------------------------
# Catalogo de tipos de evento
# ---------------------------------------------------------------------------
TIPOS_EVENTO = [
    {"codigo": "E130", "descricao": "Disparo de alarme - intrusao", "categoria": "alarme", "prioridade": "alta"},
    {"codigo": "E120", "descricao": "Panico", "categoria": "alarme", "prioridade": "critica"},
    {"codigo": "E110", "descricao": "Incendio", "categoria": "alarme", "prioridade": "critica"},
    {"codigo": "E137", "descricao": "Violacao de equipamento (tamper)", "categoria": "tecnico", "prioridade": "alta"},
    {"codigo": "E350", "descricao": "Falha de comunicacao", "categoria": "tecnico", "prioridade": "alta"},
    {"codigo": "E301", "descricao": "Falta de energia eletrica (AC)", "categoria": "tecnico", "prioridade": "media"},
    {"codigo": "E302", "descricao": "Bateria baixa", "categoria": "tecnico", "prioridade": "baixa"},
    {"codigo": "E401", "descricao": "Desarme do sistema (abertura)", "categoria": "informativo", "prioridade": "informativa"},
    {"codigo": "R401", "descricao": "Arme do sistema (fechamento)", "categoria": "informativo", "prioridade": "informativa"},
    {"codigo": "E602", "descricao": "Teste periodico", "categoria": "informativo", "prioridade": "informativa"},
]
PRIORIDADE = {t["codigo"]: t["prioridade"] for t in TIPOS_EVENTO}
INFORMATIVOS = {"E401", "R401", "E602"}
MEDIANA_ATEND = {"critica": 90, "alta": 240, "media": 600, "baixa": 1500}

OPERADORES_DIA = ["Carla Mendes", "Diego Ramos", "Fernanda Luz"]
OPERADORES_NOITE = ["Rafael Prado", "Juliana Teixeira", "Bruno Kessler"]
FATOR_OPERADOR = {"Bruno Kessler": 1.9, "Fernanda Luz": 0.8}

CIDADES = ["Porto Alegre", "Canoas", "Gravatai", "Cachoeirinha", "Viamao",
           "Alvorada", "Novo Hamburgo", "Sao Leopoldo"]
CIDADE_SUJA = {
    "Porto Alegre": ["POA", "porto alegre", "Porto Alegre "],
    "Sao Leopoldo": ["São Leopoldo", "S. Leopoldo"],
    "Gravatai": ["Gravataí", "GRAVATAI"],
    "Viamao": ["Viamão"],
    "Canoas": [" Canoas", "CANOAS"],
}


# ---------------------------------------------------------------------------
# Geracao deterministica dos dados
# ---------------------------------------------------------------------------
def gerar_clientes():
    rng = random.Random(SEED)
    comercios = ["Farmacia", "Mercado", "Padaria", "Auto Pecas", "Clinica", "Escritorio",
                 "Loja", "Restaurante", "Deposito", "Colegio", "Academia", "Pet Shop",
                 "Otica", "Distribuidora"]
    nomes = ["Bom Preco", "Santa Clara", "Primavera", "Horizonte", "Dois Irmaos", "Central",
             "Nova Era", "Bela Vista", "Sao Jorge", "Aurora", "Rio Branco", "Sol Nascente",
             "Vitoria", "Estrela", "Jardim", "Ipiranga", "Moinhos", "Lagoa"]
    sobrenomes = ["Silva", "Souza", "Oliveira", "Pereira", "Lima", "Ferreira", "Almeida",
                  "Rodrigues", "Martins", "Rocha", "Barbosa", "Cardoso", "Teixeira", "Moraes",
                  "Ribeiro"]
    industrias = ["Metalurgica", "Industria de Plasticos", "Moveis", "Embalagens", "Usinagem", "Textil"]

    plano_w = (["Basico"] * 5) + (["Plus"] * 3) + (["Premium"] * 2)
    tipos = (["residencial"] * 15) + (["comercial"] * 18) + (["agencia_bancaria"] * 6) + (["industrial"] * 6)
    usados = set()
    clientes = []
    for i, tipo in enumerate(tipos, start=1):
        while True:
            if tipo == "residencial":
                nome = "Residencia " + rng.choice(sobrenomes)
                if nome in usados:
                    nome += " " + rng.choice(["II", "(Casa de praia)", "- Ap 302", "- Ap 1101"])
            elif tipo == "comercial":
                nome = "%s %s" % (rng.choice(comercios), rng.choice(nomes))
            elif tipo == "agencia_bancaria":
                nome = "Agencia Bancaria %04d" % rng.randint(100, 2999)
            else:
                nome = "%s %s Ltda" % (rng.choice(industrias), rng.choice(nomes))
            if nome not in usados:
                usados.add(nome)
                break
        cidade = rng.choices(CIDADES, weights=[40, 12, 10, 8, 8, 6, 8, 8])[0]
        plano = "Premium" if tipo == "agencia_bancaria" else rng.choice(plano_w)
        inicio = date(2019, 1, 1) + timedelta(days=rng.randint(0, 2300))
        clientes.append({
            "id": "CLI-%04d" % i,
            "nome": nome,
            "tipo": tipo,
            "cidade": cidade,
            "plano": plano,
            "inicio_contrato": inicio.isoformat(),
            "ativo": True,
            "data_cancelamento": None,
            # atributos ocultos que geram padroes (nao vao para a API)
            "_hora_teste": rng.randint(0, 23 * 60 + 59),
        })
    # perfis especiais (ocultos)
    idx = list(range(len(clientes)))
    rng.shuffle(idx)
    for k in idx[0:3]:
        clientes[k]["_comunicacao_ruim"] = True     # falha de comunicacao cronica
    for k in idx[3:5]:
        clientes[k]["_sensor_defeito"] = True       # muitos falsos alarmes
    for k in idx[5:7]:
        clientes[k]["_bateria_fraca"] = True
    for k in idx[7:9]:
        clientes[k]["_cancela"] = True              # cancela contrato no periodo
    return clientes


def _iso_local(dt):
    return dt.astimezone(TZ_BR).isoformat(timespec="seconds")


def _iso_utc(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _quando(dia, minutos, rng, jitter=0):
    m = max(0, min(24 * 60 - 1, minutos + (rng.randint(-jitter, jitter) if jitter else 0)))
    return datetime.combine(dia, dtime(m // 60, m % 60, rng.randint(0, 59)), tzinfo=TZ_BR)


def _hora_alarme(dia, rng):
    # intrusao e mais comum de madrugada
    h = rng.choices(range(24), weights=[8, 9, 9, 8, 6, 4, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 3, 3, 4, 5, 6, 7, 8])[0]
    return datetime.combine(dia, dtime(h, rng.randint(0, 59), rng.randint(0, 59)), tzinfo=TZ_BR)


def _hora_qualquer(dia, rng):
    return datetime.combine(dia, dtime(rng.randint(0, 23), rng.randint(0, 59), rng.randint(0, 59)), tzinfo=TZ_BR)


def _atendimento(codigo, dt, cli, rng):
    """Preenche operador, tempo e resultado de um evento que exige atendimento."""
    noite = dt.hour >= 19 or dt.hour < 7
    operador = rng.choice(OPERADORES_NOITE if noite else OPERADORES_DIA)
    pr = PRIORIDADE[codigo]
    tempo = MEDIANA_ATEND[pr] * rng.lognormvariate(0, 0.5) * FATOR_OPERADOR.get(operador, 1.0)
    tempo = int(max(20, tempo))
    espera = rng.randint(15, 150)
    if codigo == "E130":
        if cli.get("_sensor_defeito"):
            res = rng.choices(["falso_alarme", "cliente_contatado"], [95, 5])[0]
        else:
            res = rng.choices(["falso_alarme", "cliente_contatado", "viatura_enviada", "policia_acionada"],
                              [75, 15, 8, 2])[0]
    elif codigo == "E120":
        res = rng.choices(["viatura_enviada", "policia_acionada", "falso_alarme"], [60, 30, 10])[0]
    elif codigo == "E110":
        res = rng.choices(["bombeiros_acionados", "falso_alarme", "cliente_contatado"], [40, 40, 20])[0]
    else:
        res = rng.choices(["cliente_contatado", "tecnico_agendado", "sem_contato"], [50, 30, 20])[0]
    return operador, espera, tempo, res


def _novo_evento(cli, codigo, dt, rng):
    ev = {"cliente_id": cli["id"], "codigo_evento": codigo, "_dt": dt,
          "zona": rng.randint(1, 8) if codigo in ("E130", "E120", "E110", "E137") else None,
          "observacao": None}
    if codigo in INFORMATIVOS:
        ev.update(status="registrado", operador=None, tempo_atendimento_seg=None, resultado=None,
                  _espera=0, _tempo=0)
    else:
        op, espera, tempo, res = _atendimento(codigo, dt, cli, rng)
        ev.update(status="encerrado", operador=op, tempo_atendimento_seg=tempo, resultado=res,
                  _espera=espera, _tempo=tempo)
        if rng.random() < 0.15:
            ev["observacao"] = rng.choice([
                "Cliente informou que esqueceu de desarmar.", "Sem contato nos telefones cadastrados.",
                "Gato dentro do imovel.", "Funcionario da limpeza.", "Vento abriu a janela.",
                "Contato com responsavel, tudo normal.", "Agendada visita tecnica.",
                "Queda de energia no bairro.", "Sensor com mau funcionamento.",
            ])
    return ev


def gerar_historico(data_fim):
    """Gera os eventos 'limpos' (verdade) dos DIAS_HISTORICO dias antes de data_fim (exclusivo)."""
    clientes = gerar_clientes()
    rng = random.Random(SEED * 7 + 1)
    inicio = data_fim - timedelta(days=DIAS_HISTORICO)
    dias = [inicio + timedelta(days=i) for i in range(DIAS_HISTORICO)]

    # dias de temporal: falta de energia em massa em 1-2 cidades
    rng_t = random.Random(SEED + 99)
    dias_temporal = {}
    for d in sorted(rng_t.sample(range(5, DIAS_HISTORICO - 2), 3)):
        dias_temporal[d] = rng_t.sample(CIDADES[:5], 2)

    # cancelamentos
    for cli in clientes:
        if cli.get("_cancela"):
            cancel = inicio + timedelta(days=rng.randint(30, 70))
            cli["ativo"] = False
            cli["data_cancelamento"] = cancel.isoformat()

    eventos = []
    for di, dia in enumerate(dias):
        dow = dia.weekday()  # 0=seg 6=dom
        for cli in clientes:
            if cli["data_cancelamento"] and dia >= date.fromisoformat(cli["data_cancelamento"]):
                continue
            tipo = cli["tipo"]
            add = lambda c, dt: eventos.append(_novo_evento(cli, c, dt, rng))

            # teste periodico diario (falha mais para comunicacao ruim)
            falha_teste = 0.35 if cli.get("_comunicacao_ruim") else 0.02
            if rng.random() > falha_teste:
                add("E602", _quando(dia, cli["_hora_teste"], rng))

            # arme / desarme
            if tipo == "residencial":
                ciclos = 1 if dow < 5 else (1 if rng.random() < 0.4 else 0)
                for _ in range(ciclos):
                    add("R401", _quando(dia, 7 * 60 + 45, rng, 50))
                    add("E401", _quando(dia, 18 * 60 + 30, rng, 70))
            else:
                abre = dow < 5 or (dow == 5 and tipo == "comercial" and rng.random() < 0.6)
                if tipo == "industrial" and dow == 5:
                    abre = rng.random() < 0.3
                if abre:
                    add("E401", _quando(dia, (8 * 60 if dow < 5 else 8 * 60 + 30), rng, 40))
                    add("R401", _quando(dia, (18 * 60 + 45 if dow < 5 else 12 * 60 + 30), rng, 60))

            # intrusao
            base = {"residencial": 0.025, "comercial": 0.045, "agencia_bancaria": 0.035, "industrial": 0.055}[tipo]
            if dow >= 5:
                base *= 1.6
            if cli.get("_sensor_defeito"):
                base = 0.45
            if rng.random() < base:
                add("E130", _hora_alarme(dia, rng))
            if rng.random() < 0.003:
                add("E120", _hora_qualquer(dia, rng))
            if rng.random() < 0.0012:
                add("E110", _hora_qualquer(dia, rng))
            if rng.random() < 0.004:
                add("E137", _hora_qualquer(dia, rng))

            # tecnicos
            p350 = 0.55 if cli.get("_comunicacao_ruim") else 0.015
            p301 = 0.008
            p302 = 0.25 if cli.get("_bateria_fraca") else 0.006
            if di in dias_temporal and cli["cidade"] in dias_temporal[di]:
                p301, p350 = 0.75, max(p350, 0.25)
                hora_temporal = datetime.combine(dia, dtime(rng.choice([15, 16, 17, 18]), 0), tzinfo=TZ_BR)
                if rng.random() < p301:
                    add("E301", hora_temporal + timedelta(minutes=rng.randint(0, 90), seconds=rng.randint(0, 59)))
                    p301 = 0
                if rng.random() < p350:
                    add("E350", hora_temporal + timedelta(minutes=rng.randint(10, 150), seconds=rng.randint(0, 59)))
                    p350 = 0
            if rng.random() < p350:
                add("E350", _hora_qualquer(dia, rng))
            if rng.random() < p301:
                add("E301", _hora_qualquer(dia, rng))
            if rng.random() < p302:
                add("E302", _hora_qualquer(dia, rng))

    eventos.sort(key=lambda e: (e["_dt"], e["cliente_id"], e["codigo_evento"]))
    for i, ev in enumerate(eventos):
        ev["id"] = 100001 + i
        ev["_atualizado"] = ev["_dt"] + timedelta(seconds=ev["_espera"] + ev["_tempo"])
    meta = {"inicio": inicio, "fim": data_fim, "dias_temporal": {
        (inicio + timedelta(days=d)).isoformat(): c for d, c in dias_temporal.items()}}
    return clientes, eventos, meta


# ---------------------------------------------------------------------------
# "Sujeira" aplicada na saida da API (deterministica)
# ---------------------------------------------------------------------------
def _sujar_evento(ev, rng):
    out = {
        "id": ev["id"],
        "cliente_id": ev["cliente_id"],
        "codigo_evento": ev["codigo_evento"],
        "zona": ev["zona"],
        "data_hora": _iso_local(ev["_dt"]),
        "status": ev["status"],
        "operador": ev["operador"],
        "tempo_atendimento_seg": ev["tempo_atendimento_seg"],
        "resultado": ev["resultado"],
        "observacao": ev["observacao"],
        "atualizado_em": _iso_utc(ev["_atualizado"]),
    }
    r = rng.random
    if r() < 0.08:  # formato de data diferente (hora local, sem fuso)
        out["data_hora"] = ev["_dt"].astimezone(TZ_BR).strftime("%d/%m/%Y %H:%M:%S")
    if r() < 0.03:
        out["codigo_evento"] = rng.choice([out["codigo_evento"].lower(), out["codigo_evento"] + " "])
    if out["status"] == "encerrado" and r() < 0.06:
        out["status"] = rng.choice(["ENCERRADO", "Encerrado", "fechado"])
    elif out["status"] == "registrado" and r() < 0.02:
        out["status"] = "REGISTRADO"
    if out["operador"] and r() < 0.04:
        out["operador"] = rng.choice([out["operador"].upper(), out["operador"] + "  ", out["operador"].split()[0]])
    if out["tempo_atendimento_seg"] is not None:
        x = r()
        if x < 0.005:
            out["tempo_atendimento_seg"] = -out["tempo_atendimento_seg"]
        elif x < 0.025:
            out["tempo_atendimento_seg"] = str(out["tempo_atendimento_seg"])
        elif x < 0.035:
            out["tempo_atendimento_seg"] = None
    if r() < 0.003:
        out["cliente_id"] = rng.choice(["CLI-9999", "CLI-0000", out["cliente_id"].lower()])
    return out


def montar_saida_historico(eventos):
    rng = random.Random(SEED + 555)
    saida = []
    for ev in eventos:
        o = _sujar_evento(ev, rng)
        saida.append(o)
        if rng.random() < 0.015:  # duplicata exata
            saida.append(dict(o))
    return saida


def clientes_publicos(clientes):
    rng = random.Random(SEED + 3)
    pub = []
    for c in clientes:
        d = {k: v for k, v in c.items() if not k.startswith("_")}
        if d["cidade"] in CIDADE_SUJA and rng.random() < 0.45:
            d["cidade"] = rng.choice(CIDADE_SUJA[d["cidade"]])
        if rng.random() < 0.1:
            d["nome"] = d["nome"].upper()
        pub.append(d)
    return pub


# ---------------------------------------------------------------------------
# Eventos "ao vivo" (de 00:00 de hoje em diante)
# ---------------------------------------------------------------------------
class FluxoAoVivo:
    def __init__(self, clientes, hoje, primeiro_id):
        self.clientes = [c for c in clientes if c["ativo"]]
        self.rng = random.Random(SEED * 31 + hoje.toordinal())
        self.rng_sujo = random.Random(SEED * 17 + hoje.toordinal())
        self.cursor = datetime.combine(hoje, dtime(0, 0), tzinfo=TZ_BR)
        self.prox_id = primeiro_id
        self.eventos = []
        self.lock = threading.Lock()

    def _avancar(self, agora):
        codigos = ["E602", "R401", "E401", "E130", "E350", "E301", "E302", "E137", "E120"]
        pesos = [30, 25, 25, 3, 2, 1, 1, 0.4, 0.15]
        while True:
            prox = self.cursor + timedelta(seconds=self.rng.randint(90, 600))
            if prox > agora:
                break
            self.cursor = prox
            cli = self.rng.choice(self.clientes)
            ev = _novo_evento(cli, self.rng.choices(codigos, pesos)[0], prox, self.rng)
            ev["id"] = self.prox_id
            ev["_atualizado"] = prox + timedelta(seconds=ev["_espera"] + ev["_tempo"])
            self.prox_id += 1
            ev["_sujo"] = _sujar_evento(ev, self.rng_sujo)
            self.eventos.append(ev)

    def visao(self, agora):
        """Retorna os eventos ao vivo como estao AGORA (status evolui com o tempo)."""
        with self.lock:
            self._avancar(agora)
            lista = list(self.eventos)
        out = []
        for ev in lista:
            o = dict(ev["_sujo"])
            if ev["codigo_evento"] not in INFORMATIVOS:
                t1 = ev["_dt"] + timedelta(seconds=ev["_espera"])
                t2 = t1 + timedelta(seconds=ev["_tempo"])
                if agora < t1:
                    o.update(status="aberto", operador=None, tempo_atendimento_seg=None,
                             resultado=None, observacao=None, atualizado_em=_iso_utc(ev["_dt"]))
                elif agora < t2:
                    o.update(status="em_atendimento", tempo_atendimento_seg=None,
                             resultado=None, observacao=None, atualizado_em=_iso_utc(t1))
                else:
                    o["atualizado_em"] = _iso_utc(t2)
            out.append(o)
        return out


# ---------------------------------------------------------------------------
# Servidor HTTP
# ---------------------------------------------------------------------------
class Estado:
    pass


EST = Estado()


def _parse_iso(s):
    s = s.strip().replace(" ", "+")  # '+' pode virar espaco na URL
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class Handler(BaseHTTPRequestHandler):
    server_version = "CentralMonitoramentoMock/1.0"

    def log_message(self, fmt, *args):
        if not EST.silencioso:
            super().log_message(fmt, *args)

    def _json(self, code, obj, headers=None):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _autorizado(self):
        if self.headers.get("X-API-Key") != API_KEY:
            self._json(401, {"erro": "nao_autorizado", "mensagem": "Envie o cabecalho X-API-Key valido."})
            return False
        return True

    def _rate_limit(self):
        agora = time.monotonic()
        with EST.lock_rl:
            while EST.janela and agora - EST.janela[0] > 1.0:
                EST.janela.popleft()
            if len(EST.janela) >= LIMITE_REQ_POR_SEG:
                self._json(429, {"erro": "limite_excedido",
                                 "mensagem": "Maximo de %d requisicoes por segundo." % LIMITE_REQ_POR_SEG},
                           {"Retry-After": "2"})
                return False
            EST.janela.append(agora)
        return True

    def _instabilidade(self):
        r = EST.rng_falhas.random()
        if r < EST.taxa_falhas:
            self._json(503, {"erro": "servico_indisponivel", "mensagem": "Tente novamente em instantes."})
            return True
        if r < EST.taxa_falhas + EST.taxa_lentidao:
            time.sleep(6)
        return False

    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[-1] for k, v in parse_qs(url.query).items()}
        rota = url.path.rstrip("/") or "/"

        if rota == "/":
            return self._json(200, {"api": "Central de Monitoramento (mock)", "versao": "1.0",
                                    "documentacao": "Leia o arquivo README_API.md",
                                    "endpoints": ["/api/v1/saude", "/api/v1/clientes",
                                                  "/api/v1/tipos-evento", "/api/v1/eventos"]})
        if rota == "/api/v1/saude":
            return self._json(200, {"status": "ok", "agora": _iso_utc(datetime.now(timezone.utc)),
                                    "historico_inicio": EST.meta["inicio"].isoformat(),
                                    "historico_fim": (EST.meta["fim"] - timedelta(days=1)).isoformat(),
                                    "ao_vivo_desde": EST.meta["fim"].isoformat() + "T00:00:00-03:00"})

        if rota not in ("/api/v1/clientes", "/api/v1/tipos-evento", "/api/v1/eventos"):
            return self._json(404, {"erro": "nao_encontrado"})
        if not self._autorizado() or not self._rate_limit():
            return
        if rota == "/api/v1/clientes":
            return self._json(200, {"dados": EST.clientes_pub})
        if rota == "/api/v1/tipos-evento":
            return self._json(200, {"dados": TIPOS_EVENTO})

        # /api/v1/eventos
        if self._instabilidade():
            return
        try:
            pagina = int(q.get("pagina", 1))
            por_pagina = int(q.get("por_pagina", POR_PAGINA_PADRAO))
            if pagina < 1 or not (1 <= por_pagina <= POR_PAGINA_MAX):
                raise ValueError
        except ValueError:
            return self._json(400, {"erro": "parametro_invalido",
                                    "mensagem": "pagina >= 1 e 1 <= por_pagina <= %d" % POR_PAGINA_MAX})
        desde = None
        if "atualizado_desde" in q:
            try:
                desde = _parse_iso(q["atualizado_desde"])
            except ValueError:
                return self._json(400, {"erro": "parametro_invalido",
                                        "mensagem": "atualizado_desde deve ser ISO 8601, ex: 2026-10-01T00:00:00Z"})
        agora = datetime.now(timezone.utc)
        dados = EST.hist_saida + EST.ao_vivo.visao(agora)
        if desde is not None:
            limite = _iso_utc(desde)
            dados = [d for d in dados if d["atualizado_em"] >= limite]
        dados.sort(key=lambda d: (d["atualizado_em"], d["id"]))
        total = len(dados)
        total_paginas = max(1, -(-total // por_pagina))
        ini = (pagina - 1) * por_pagina
        return self._json(200, {"pagina": pagina, "por_pagina": por_pagina, "total_registros": total,
                                "total_paginas": total_paginas, "dados": dados[ini:ini + por_pagina]})


def preparar(hoje=None, taxa_falhas=0.05, taxa_lentidao=0.02, silencioso=False):
    hoje = hoje or datetime.now(TZ_BR).date()
    clientes, eventos, meta = gerar_historico(hoje)
    EST.meta = meta
    EST.clientes_pub = clientes_publicos(clientes)
    EST.hist_saida = montar_saida_historico(eventos)
    EST.ao_vivo = FluxoAoVivo(clientes, hoje, eventos[-1]["id"] + 1)
    EST.lock_rl = threading.Lock()
    EST.janela = deque()
    EST.rng_falhas = random.Random()
    EST.taxa_falhas = taxa_falhas
    EST.taxa_lentidao = taxa_lentidao
    EST.silencioso = silencioso
    return clientes, eventos, meta


def main():
    ap = argparse.ArgumentParser(description="API mock - Central de Monitoramento")
    ap.add_argument("--porta", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--silencioso", action="store_true", help="nao imprime cada requisicao")
    args = ap.parse_args()
    _, eventos, meta = preparar(silencioso=args.silencioso)
    print("=" * 64)
    print(" API mock - Central de Monitoramento")
    print(" http://%s:%d   (X-API-Key: %s)" % (args.host, args.porta, API_KEY))
    print(" Historico: %s a %s  |  + eventos ao vivo a partir de hoje 00:00"
          % (meta["inicio"], meta["fim"] - timedelta(days=1)))
    print(" Ctrl+C para parar")
    print("=" * 64)
    srv = ThreadingHTTPServer((args.host, args.porta), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrado.")


if __name__ == "__main__":
    main()
