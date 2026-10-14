"""Aplicação Flask do painel.

Uma página (``templates/painel.html``) com o visual do design system e dois
endpoints JSON que o JavaScript da página consome:

- ``GET /api/painel?inicio=&fim=&cidade=&tipo=``: todos os indicadores do período.
- ``GET /api/agora?cidade=&tipo=``: eventos abertos neste momento e a situação da
  captura. É consultado de novo a cada minuto, sem recarregar a página.

O plotly.js é servido a partir do pacote Python ``plotly`` (``/static/vendor/plotly.min.js``),
então o painel funciona sem internet.
"""
import logging
import sqlite3
from datetime import date, timedelta
from typing import Optional

from flask import Flask, Response, g, jsonify, render_template, request

from central import banco, config
from . import consultas
from .consultas import Filtros

log = logging.getLogger(__name__)

DIAS_PADRAO = 30


def _con() -> sqlite3.Connection:
    if "con" not in g:
        g.con = banco.conectar(config.CAMINHO_BANCO)
    return g.con


def _data(valor: Optional[str], padrao: str) -> str:
    if not valor:
        return padrao
    try:
        return date.fromisoformat(valor).isoformat()
    except ValueError:
        return padrao


def _filtros(con: sqlite3.Connection) -> Filtros:
    fim_padrao = consultas.data_maxima(con) or date.today().isoformat()
    inicio_padrao = (date.fromisoformat(fim_padrao) - timedelta(days=DIAS_PADRAO - 1)).isoformat()
    inicio = _data(request.args.get("inicio"), inicio_padrao)
    fim = _data(request.args.get("fim"), fim_padrao)
    if inicio > fim:
        inicio, fim = fim, inicio
    return Filtros(
        inicio=inicio, fim=fim,
        cidade=request.args.get("cidade") or None,
        tipo=request.args.get("tipo") or None,
    )


def criar_app() -> Flask:
    app = Flask(__name__)

    @app.teardown_appcontext
    def fechar(_exc):
        con = g.pop("con", None)
        if con is not None:
            con.close()

    @app.get("/")
    def pagina():
        con = _con()
        return render_template("painel.html",
                               opcoes=consultas.opcoes(con),
                               situacao=consultas.situacao_captura(con),
                               dias_padrao=DIAS_PADRAO)

    @app.get("/static/vendor/plotly.min.js")
    def plotly_js():
        import plotly.offline
        resposta = Response(plotly.offline.get_plotlyjs(), mimetype="application/javascript")
        resposta.headers["Cache-Control"] = "public, max-age=86400"
        return resposta

    @app.get("/api/painel")
    def api_painel():
        con = _con()
        f = _filtros(con)
        return jsonify({
            "filtros": f.__dict__,
            "resumo": consultas.resumo(con, f),
            "volume_por_dia": consultas.volume_por_dia(con, f),
            "volume_por_tipo": consultas.volume_por_tipo(con, f),
            "abertos": consultas.abertos_agora(con, f),
            "tempo_por_prioridade": consultas.tempo_por_prioridade(con, f),
            "tempo_por_operador": consultas.tempo_por_operador(con, f),
            "carga_por_turno": consultas.carga_por_turno(con, f),
            "tempo_por_resultado": consultas.tempo_por_resultado(con, f),
            "ranking_disparos": consultas.ranking_disparos(con, f),
            "problemas_tecnicos": consultas.problemas_tecnicos(con, f),
            "disparos_por_hora": consultas.disparos_por_hora(con, f),
            "energia_por_dia": consultas.energia_por_dia(con, f),
            "testes_ausentes": consultas.testes_ausentes(con, f),
            "qualidade": consultas.qualidade(con),
            "situacao": consultas.situacao_captura(con),
        })

    @app.get("/monitoramento")
    def monitoramento():
        con = _con()
        return render_template("monitor.html", opcoes=consultas.opcoes(con))

    @app.get("/api/monitor")
    def api_monitor():
        con = _con()
        f = _filtros(con)
        return jsonify({
            "abertos": consultas.abertos_agora(con, f),
            "situacao": consultas.situacao_captura(con),
            "hoje": consultas.resumo_do_dia(con, f),
            "ultimas_24h": consultas.eventos_ultimas_24h(con, f),
            "encerrados": consultas.ultimos_encerrados(con, f),
        })

    @app.get("/api/agora")
    def api_agora():
        con = _con()
        f = _filtros(con)
        return jsonify({
            "abertos": consultas.abertos_agora(con, f),
            "situacao": consultas.situacao_captura(con),
        })

    return app
