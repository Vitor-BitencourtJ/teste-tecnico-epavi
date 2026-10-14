"""Consultas que alimentam o painel.

Cada função recebe a conexão e um ``Filtros`` e devolve listas/dicionários
prontos para virar JSON. Toda a conta fica no SQL, para o número do painel ser
reproduzível com uma consulta no banco.

Convenções:
- ``data_hora`` está em horário de Brasília ('AAAA-MM-DD HH:MM:SS'), então
  ``date(data_hora)`` é o dia operacional.
- Eventos de cliente desconhecido (CLI-0000/CLI-9999) entram no volume geral e
  nos tempos de atendimento, mas saem assim que o filtro de cidade ou tipo é
  aplicado (não dá para saber a cidade deles) e nunca entram em ranking por cliente.
"""
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

CATEGORIAS = ("alarme", "tecnico", "informativo")
STATUS_ABERTOS = ("aberto", "em_atendimento")
CODIGOS_TECNICOS = {"E350": "comunicacao", "E301": "energia", "E302": "bateria"}


@dataclass(frozen=True)
class Filtros:
    inicio: str                      # 'AAAA-MM-DD' inclusive
    fim: str                         # 'AAAA-MM-DD' inclusive
    cidade: Optional[str] = None
    tipo: Optional[str] = None

    def where(self, com_periodo: bool = True) -> str:
        partes = []
        if com_periodo:
            partes.append("date(e.data_hora) BETWEEN :inicio AND :fim")
        if self.cidade:
            partes.append("c.cidade = :cidade")
        if self.tipo:
            partes.append("c.tipo = :tipo")
        return " AND ".join(partes) or "1=1"

    def params(self) -> Dict:
        return {"inicio": self.inicio, "fim": self.fim, "cidade": self.cidade, "tipo": self.tipo}


# Junção padrão: evento + cliente (pode não existir) + tipo do evento.
DE = """
FROM eventos e
LEFT JOIN clientes c ON c.id = e.cliente_id
LEFT JOIN tipos_evento t ON t.codigo = e.codigo_evento
"""


def _linhas(con: sqlite3.Connection, sql: str, params: Dict = None) -> List[Dict]:
    return [dict(l) for l in con.execute(sql, params or {})]


def _uma(con: sqlite3.Connection, sql: str, params: Dict = None) -> Dict:
    return dict(con.execute(sql, params or {}).fetchone())


# ---------------------------------------------------------------------------
# Opções e situação da captura
# ---------------------------------------------------------------------------
def opcoes(con: sqlite3.Connection) -> Dict:
    faixa = _uma(con, "SELECT MIN(date(data_hora)) AS inicio, MAX(date(data_hora)) AS fim FROM eventos")
    return {
        "cidades": [l["cidade"] for l in con.execute("SELECT DISTINCT cidade FROM clientes ORDER BY 1")],
        "tipos": [l["tipo"] for l in con.execute("SELECT DISTINCT tipo FROM clientes ORDER BY 1")],
        "data_minima": faixa["inicio"],
        "data_maxima": faixa["fim"],
    }


def situacao_captura(con: sqlite3.Connection) -> Dict:
    ultima = con.execute(
        "SELECT id, fim, status, modo, marca_dagua FROM execucoes ORDER BY id DESC LIMIT 1").fetchone()
    if not ultima:
        return {"existe": False}
    minutos = None
    if ultima["fim"]:
        fim = datetime.strptime(ultima["fim"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        minutos = int((datetime.now(timezone.utc) - fim).total_seconds() // 60)
    ultimo_evento = con.execute("SELECT MAX(data_hora) FROM eventos").fetchone()[0]
    return {"existe": True, "execucao": ultima["id"], "status": ultima["status"], "modo": ultima["modo"],
            "fim": ultima["fim"], "minutos_atras": minutos, "marca_dagua": ultima["marca_dagua"],
            "ultimo_evento": ultimo_evento}


# ---------------------------------------------------------------------------
# 1. Visão geral
# ---------------------------------------------------------------------------
def resumo(con: sqlite3.Connection, f: Filtros) -> Dict:
    sql = f"""
    SELECT COUNT(*)                                                     AS eventos,
           SUM(t.categoria = 'alarme')                                  AS alarmes,
           SUM(e.codigo_evento = 'E130')                                AS disparos,
           SUM(e.codigo_evento = 'E130' AND e.resultado = 'falso_alarme') AS disparos_falsos,
           SUM(t.categoria = 'tecnico')                                 AS tecnicos,
           AVG(CASE WHEN e.status = 'encerrado' THEN e.tempo_atendimento_seg END) AS tempo_medio_seg,
           SUM(e.status = 'encerrado')                                  AS atendidos
    {DE} WHERE {f.where()}"""
    atual = _uma(con, sql, f.params())

    # Período anterior de mesmo tamanho, para os chips de variação. O SQL é o
    # mesmo; só mudam as datas passadas como parâmetro.
    inicio = date.fromisoformat(f.inicio)
    dias = (date.fromisoformat(f.fim) - inicio).days + 1
    anterior_f = Filtros(inicio=(inicio - timedelta(days=dias)).isoformat(),
                         fim=(inicio - timedelta(days=1)).isoformat(),
                         cidade=f.cidade, tipo=f.tipo)
    anterior = _uma(con, sql, anterior_f.params())

    abertos = _uma(con, f"""
    SELECT COUNT(*) AS n {DE}
    WHERE e.status IN ('aberto', 'em_atendimento') AND {f.where(com_periodo=False)}""", f.params())

    return {"atual": atual, "anterior": anterior, "abertos_agora": abertos["n"], "dias": dias}


def volume_por_dia(con: sqlite3.Connection, f: Filtros) -> List[Dict]:
    return _linhas(con, f"""
    SELECT date(e.data_hora) AS dia, t.categoria, COUNT(*) AS n
    {DE} WHERE {f.where()}
    GROUP BY 1, 2 ORDER BY 1""", f.params())


def volume_por_tipo(con: sqlite3.Connection, f: Filtros) -> List[Dict]:
    return _linhas(con, f"""
    SELECT e.codigo_evento AS codigo, t.descricao, t.categoria, t.prioridade, COUNT(*) AS n
    {DE} WHERE {f.where()}
    GROUP BY 1 ORDER BY n DESC""", f.params())


# ---------------------------------------------------------------------------
# 2. Agora
# ---------------------------------------------------------------------------
def abertos_agora(con: sqlite3.Connection, f: Filtros) -> List[Dict]:
    return _linhas(con, f"""
    SELECT e.id, e.cliente_id, c.nome AS cliente, c.cidade, c.tipo AS tipo_cliente,
           e.codigo_evento, t.descricao, t.prioridade, e.status, e.zona, e.data_hora, e.operador,
           CAST((julianday('now', 'localtime') - julianday(e.data_hora)) * 24 * 60 AS INTEGER) AS minutos
    {DE}
    WHERE e.status IN ('aberto', 'em_atendimento') AND {f.where(com_periodo=False)}
    ORDER BY e.data_hora""", f.params())


# ---------------------------------------------------------------------------
# 3. Atendimento
# ---------------------------------------------------------------------------
def tempo_por_prioridade(con: sqlite3.Connection, f: Filtros) -> List[Dict]:
    return _linhas(con, f"""
    SELECT t.prioridade, COUNT(*) AS atendimentos,
           AVG(e.tempo_atendimento_seg) AS media_seg, MAX(e.tempo_atendimento_seg) AS maximo_seg
    {DE}
    WHERE e.status = 'encerrado' AND e.tempo_atendimento_seg IS NOT NULL AND {f.where()}
    GROUP BY 1
    ORDER BY CASE t.prioridade WHEN 'critica' THEN 1 WHEN 'alta' THEN 2 WHEN 'media' THEN 3 ELSE 4 END""",
                   f.params())


def tempo_por_operador(con: sqlite3.Connection, f: Filtros) -> List[Dict]:
    """Média por operador e, para comparar com justiça, a média que seria esperada
    pela mistura de prioridades que ele atendeu (média geral de cada prioridade)."""
    return _linhas(con, f"""
    WITH base AS (
        SELECT e.operador, t.prioridade, e.tempo_atendimento_seg AS seg,
               CAST(strftime('%H', e.data_hora) AS INTEGER) AS hora
        {DE}
        WHERE e.status = 'encerrado' AND e.tempo_atendimento_seg IS NOT NULL
          AND e.operador IS NOT NULL AND {f.where()}
    ),
    geral AS (SELECT prioridade, AVG(seg) AS media_prioridade FROM base GROUP BY 1)
    SELECT b.operador, COUNT(*) AS atendimentos,
           AVG(b.seg) AS media_seg,
           AVG(g.media_prioridade) AS esperado_seg,
           AVG(b.hora >= 19 OR b.hora < 7) AS fracao_noite
    FROM base b JOIN geral g ON g.prioridade = b.prioridade
    GROUP BY 1 ORDER BY media_seg DESC""", f.params())


def carga_por_turno(con: sqlite3.Connection, f: Filtros) -> List[Dict]:
    """Dia (7h às 19h) contra noite (19h às 7h): quantos atendimentos, quanto
    tempo levam e quantos disparos de intrusão cada turno recebe."""
    return _linhas(con, f"""
    WITH base AS (
        SELECT CASE WHEN CAST(strftime('%H', e.data_hora) AS INTEGER) BETWEEN 7 AND 18
                    THEN 'dia' ELSE 'noite' END AS turno,
               e.status, e.tempo_atendimento_seg, e.codigo_evento, e.operador
        {DE} WHERE {f.where()}
    )
    SELECT turno,
           SUM(status = 'encerrado' AND tempo_atendimento_seg IS NOT NULL)        AS atendimentos,
           AVG(CASE WHEN status = 'encerrado' THEN tempo_atendimento_seg END)      AS media_seg,
           SUM(codigo_evento = 'E130')                                             AS disparos,
           COUNT(DISTINCT CASE WHEN status = 'encerrado' THEN operador END)        AS operadores
    FROM base GROUP BY 1 ORDER BY 1""", f.params())


def tempo_por_resultado(con: sqlite3.Connection, f: Filtros) -> List[Dict]:
    """Para onde vai o tempo da equipe: horas de atendimento por desfecho."""
    return _linhas(con, f"""
    SELECT e.resultado, COUNT(*) AS n, AVG(e.tempo_atendimento_seg) AS media_seg,
           SUM(e.tempo_atendimento_seg) / 3600.0 AS horas
    {DE}
    WHERE e.status = 'encerrado' AND e.tempo_atendimento_seg IS NOT NULL
      AND e.resultado IS NOT NULL AND {f.where()}
    GROUP BY 1 ORDER BY horas DESC""", f.params())


# ---------------------------------------------------------------------------
# 4. Clientes
# ---------------------------------------------------------------------------
def ranking_disparos(con: sqlite3.Connection, f: Filtros, limite: int = 10) -> List[Dict]:
    return _linhas(con, f"""
    SELECT c.id, c.nome, c.cidade, c.tipo, c.plano,
           COUNT(*) AS disparos,
           SUM(e.resultado = 'falso_alarme') AS falsos,
           SUM(e.resultado IN ('viatura_enviada', 'policia_acionada')) AS acionamentos,
           COUNT(DISTINCT date(e.data_hora)) AS dias_com_disparo
    {DE}
    WHERE e.codigo_evento = 'E130' AND c.id IS NOT NULL AND {f.where()}
    GROUP BY c.id ORDER BY disparos DESC, falsos DESC LIMIT :limite""", {**f.params(), "limite": limite})


def problemas_tecnicos(con: sqlite3.Connection, f: Filtros, limite: int = 10) -> List[Dict]:
    return _linhas(con, f"""
    SELECT c.id, c.nome, c.cidade, c.tipo,
           SUM(e.codigo_evento = 'E350') AS comunicacao,
           SUM(e.codigo_evento = 'E301') AS energia,
           SUM(e.codigo_evento = 'E302') AS bateria,
           COUNT(*) AS total,
           COUNT(DISTINCT date(e.data_hora)) AS dias_com_problema
    {DE}
    WHERE e.codigo_evento IN ('E350', 'E301', 'E302') AND c.id IS NOT NULL AND {f.where()}
    GROUP BY c.id ORDER BY total DESC LIMIT :limite""", {**f.params(), "limite": limite})


# ---------------------------------------------------------------------------
# 5. Insights
# ---------------------------------------------------------------------------
def disparos_por_hora(con: sqlite3.Connection, f: Filtros) -> List[Dict]:
    return _linhas(con, f"""
    SELECT CAST(strftime('%H', e.data_hora) AS INTEGER) AS hora, COUNT(*) AS n
    {DE} WHERE e.codigo_evento = 'E130' AND {f.where()}
    GROUP BY 1 ORDER BY 1""", f.params())


def energia_por_dia(con: sqlite3.Connection, f: Filtros) -> List[Dict]:
    """Faltas de energia por dia e cidade: dias de temporal aparecem como picos."""
    return _linhas(con, f"""
    SELECT date(e.data_hora) AS dia, c.cidade, COUNT(*) AS n
    {DE} WHERE e.codigo_evento = 'E301' AND c.id IS NOT NULL AND {f.where()}
    GROUP BY 1, 2 ORDER BY 1""", f.params())


def testes_ausentes(con: sqlite3.Connection, f: Filtros, limite: int = 10) -> List[Dict]:
    """Clientes que mais ficaram dias sem mandar o teste periódico (E602).

    O painel de alarme deve testar a comunicação todo dia. Dia sem teste é um
    dia em que não sabemos se o cliente está protegido. Conta só os dias em que
    o contrato estava ativo dentro do período filtrado.
    """
    return _linhas(con, f"""
    WITH periodo AS (
        SELECT :inicio AS inicio, :fim AS fim
    ),
    dias_cliente AS (
        SELECT c.id, c.nome, c.cidade, c.tipo,
               MAX(p.inicio, c.inicio_contrato) AS de,
               MIN(p.fim, COALESCE(date(c.data_cancelamento, '-1 day'), p.fim)) AS ate
        FROM clientes c, periodo p
        WHERE (:cidade IS NULL OR c.cidade = :cidade) AND (:tipo IS NULL OR c.tipo = :tipo)
    ),
    testes AS (
        SELECT e.cliente_id, COUNT(DISTINCT date(e.data_hora)) AS dias_com_teste
        FROM eventos e WHERE e.codigo_evento = 'E602' AND date(e.data_hora) BETWEEN :inicio AND :fim
        GROUP BY 1
    ),
    falhas AS (
        SELECT e.cliente_id, COUNT(*) AS falhas_comunicacao
        FROM eventos e WHERE e.codigo_evento = 'E350' AND date(e.data_hora) BETWEEN :inicio AND :fim
        GROUP BY 1
    )
    SELECT d.id, d.nome, d.cidade, d.tipo,
           CAST(julianday(d.ate) - julianday(d.de) + 1 AS INTEGER) AS dias_ativos,
           COALESCE(t.dias_com_teste, 0) AS dias_com_teste,
           CAST(julianday(d.ate) - julianday(d.de) + 1 AS INTEGER) - COALESCE(t.dias_com_teste, 0) AS dias_sem_teste,
           COALESCE(fl.falhas_comunicacao, 0) AS falhas_comunicacao
    FROM dias_cliente d
    LEFT JOIN testes t ON t.cliente_id = d.id
    LEFT JOIN falhas fl ON fl.cliente_id = d.id
    WHERE d.ate >= d.de
    ORDER BY dias_sem_teste DESC, falhas_comunicacao DESC LIMIT :limite""", {**f.params(), "limite": limite})


# ---------------------------------------------------------------------------
# 6. Qualidade dos dados
# ---------------------------------------------------------------------------
def qualidade(con: sqlite3.Connection) -> Dict:
    totais = _uma(con, """
    SELECT (SELECT COUNT(*) FROM eventos) AS eventos,
           (SELECT COUNT(DISTINCT chave) FROM problemas_dados WHERE entidade = 'evento') AS eventos_com_correcao,
           (SELECT COUNT(*) FROM clientes) AS clientes,
           (SELECT COUNT(DISTINCT chave) FROM problemas_dados WHERE entidade = 'cliente') AS clientes_com_correcao,
           (SELECT COUNT(*) FROM eventos_rejeitados) AS rejeitados,
           (SELECT COUNT(*) FROM eventos WHERE cliente_id NOT IN (SELECT id FROM clientes)) AS sem_cliente""")
    por_problema = _linhas(con, """
    SELECT entidade, campo, problema, COUNT(*) AS n
    FROM problemas_dados GROUP BY 1, 2, 3 ORDER BY n DESC""")
    exemplos = {l["problema"]: l["valor_original"] for l in con.execute("""
    SELECT problema, MIN(valor_original) AS valor_original FROM problemas_dados
    WHERE valor_original IS NOT NULL GROUP BY 1""")}
    execucoes = _linhas(con, """
    SELECT id, inicio, fim, modo, status, registros_lidos, novos, atualizados, inalterados,
           rejeitados, com_problemas, requisicoes, retentativas, erro
    FROM execucoes ORDER BY id DESC LIMIT 12""")
    return {"totais": totais, "por_problema": por_problema, "exemplos": exemplos, "execucoes": execucoes}
