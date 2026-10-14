"""Esquema e gravação no SQLite.

Tabelas:

- ``clientes`` e ``tipos_evento``: catálogos, substituídos a cada execução.
- ``eventos``: um evento por ``id``. Gravar de novo o mesmo ``id`` **atualiza**
  a linha (o evento muda de ``aberto`` para ``encerrado``), nunca duplica.
  Guarda também o JSON original em ``bruto_json``.
- ``problemas_dados``: cada correção feita na limpeza, com o valor original.
- ``eventos_rejeitados``: registros que nem a limpeza salvou. Ficam guardados
  para não perder dado e para investigação.
- ``execucoes``: uma linha por rodada da captura, com contagens e a marca
  d'água (``marca_dagua``) usada pela próxima rodada incremental.
- ``metadados``: pares chave/valor (ex.: janela do histórico da API).
"""
import json
import sqlite3
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .normalizacao import Problema, completar_nomes

ESQUEMA = """
CREATE TABLE IF NOT EXISTS clientes (
    id                TEXT PRIMARY KEY,
    nome              TEXT NOT NULL,
    tipo              TEXT NOT NULL,
    cidade            TEXT NOT NULL,
    plano             TEXT,
    inicio_contrato   TEXT,
    ativo             INTEGER NOT NULL,
    data_cancelamento TEXT
);

CREATE TABLE IF NOT EXISTS tipos_evento (
    codigo     TEXT PRIMARY KEY,
    descricao  TEXT NOT NULL,
    categoria  TEXT NOT NULL,
    prioridade TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS eventos (
    id                    INTEGER PRIMARY KEY,
    cliente_id            TEXT NOT NULL,   -- pode nao existir em clientes (ver problemas_dados)
    codigo_evento         TEXT NOT NULL,
    zona                  INTEGER,
    data_hora             TEXT NOT NULL,   -- 'AAAA-MM-DD HH:MM:SS' em horario de Brasilia
    status                TEXT NOT NULL,   -- aberto | em_atendimento | encerrado | registrado
    operador              TEXT,
    tempo_atendimento_seg INTEGER,
    resultado             TEXT,
    observacao            TEXT,
    atualizado_em         TEXT NOT NULL,   -- UTC, como a API manda ('...Z')
    capturado_em          TEXT NOT NULL,
    bruto_json            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_eventos_data_hora ON eventos (data_hora);
CREATE INDEX IF NOT EXISTS ix_eventos_cliente   ON eventos (cliente_id);
CREATE INDEX IF NOT EXISTS ix_eventos_status    ON eventos (status);

CREATE TABLE IF NOT EXISTS problemas_dados (
    entidade       TEXT NOT NULL,          -- 'evento' | 'cliente'
    chave          TEXT NOT NULL,          -- id do evento ou do cliente
    campo          TEXT NOT NULL,
    problema       TEXT NOT NULL,
    valor_original TEXT,
    PRIMARY KEY (entidade, chave, campo, problema)
);

CREATE TABLE IF NOT EXISTS eventos_rejeitados (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    execucao_id  INTEGER NOT NULL,
    motivo       TEXT NOT NULL,
    bruto_json   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS execucoes (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    inicio            TEXT NOT NULL,
    fim               TEXT,
    modo              TEXT NOT NULL,       -- 'completa' | 'incremental'
    status            TEXT NOT NULL,       -- 'executando' | 'ok' | 'erro'
    atualizado_desde  TEXT,                -- marca d'agua usada nesta rodada
    marca_dagua       TEXT,                -- maior atualizado_em lido (para a proxima)
    registros_lidos   INTEGER DEFAULT 0,
    novos             INTEGER DEFAULT 0,
    atualizados       INTEGER DEFAULT 0,
    inalterados       INTEGER DEFAULT 0,
    ignorados         INTEGER DEFAULT 0,
    rejeitados        INTEGER DEFAULT 0,
    com_problemas     INTEGER DEFAULT 0,
    requisicoes       INTEGER DEFAULT 0,
    retentativas      INTEGER DEFAULT 0,
    erro              TEXT
);

CREATE TABLE IF NOT EXISTS metadados (
    chave TEXT PRIMARY KEY,
    valor TEXT
);
"""


def conectar(caminho: Path) -> sqlite3.Connection:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(caminho)
    con.row_factory = sqlite3.Row
    # WAL deixa o painel ler enquanto a captura escreve.
    con.execute("PRAGMA journal_mode = WAL")
    con.executescript(ESQUEMA)
    return con


def apagar(caminho: Path) -> None:
    for sufixo in ("", "-wal", "-shm"):
        arq = Path(str(caminho) + sufixo)
        if arq.exists():
            arq.unlink()


# ---------------------------------------------------------------------------
# Metadados e execuções
# ---------------------------------------------------------------------------
def ler_metadado(con: sqlite3.Connection, chave: str) -> Optional[str]:
    linha = con.execute("SELECT valor FROM metadados WHERE chave = ?", (chave,)).fetchone()
    return linha["valor"] if linha else None


def gravar_metadado(con: sqlite3.Connection, chave: str, valor: str) -> None:
    con.execute("INSERT OR REPLACE INTO metadados (chave, valor) VALUES (?, ?)", (chave, valor))


def ultima_marca_dagua(con: sqlite3.Connection) -> Optional[str]:
    """Maior ``atualizado_em`` já gravado em qualquer execução.

    Vale também para execuções que falharam no meio: tudo que ficou abaixo da
    marca já está no banco (gravamos página a página), então a próxima rodada
    pode continuar dali.
    """
    linha = con.execute(
        "SELECT marca_dagua FROM execucoes WHERE marca_dagua IS NOT NULL "
        "ORDER BY marca_dagua DESC LIMIT 1").fetchone()
    return linha["marca_dagua"] if linha else None


def iniciar_execucao(con: sqlite3.Connection, inicio: str, modo: str,
                     atualizado_desde: Optional[str]) -> int:
    cur = con.execute(
        "INSERT INTO execucoes (inicio, modo, status, atualizado_desde) VALUES (?, ?, 'executando', ?)",
        (inicio, modo, atualizado_desde))
    return cur.lastrowid


def atualizar_execucao(con: sqlite3.Connection, execucao_id: int, **campos) -> None:
    colunas = ", ".join(f"{c} = ?" for c in campos)
    con.execute(f"UPDATE execucoes SET {colunas} WHERE id = ?", (*campos.values(), execucao_id))


# ---------------------------------------------------------------------------
# Catálogos
# ---------------------------------------------------------------------------
def gravar_tipos_evento(con: sqlite3.Connection, tipos: Iterable[Dict]) -> None:
    con.executemany(
        "INSERT OR REPLACE INTO tipos_evento (codigo, descricao, categoria, prioridade) "
        "VALUES (:codigo, :descricao, :categoria, :prioridade)", tipos)


def gravar_clientes(con: sqlite3.Connection,
                    clientes: Sequence[Tuple[Dict, List[Problema]]]) -> None:
    con.executemany(
        "INSERT OR REPLACE INTO clientes "
        "(id, nome, tipo, cidade, plano, inicio_contrato, ativo, data_cancelamento) VALUES "
        "(:id, :nome, :tipo, :cidade, :plano, :inicio_contrato, :ativo, :data_cancelamento)",
        [c for c, _ in clientes])
    con.execute("DELETE FROM problemas_dados WHERE entidade = 'cliente'")
    for cliente, problemas in clientes:
        _gravar_problemas(con, "cliente", cliente["id"], problemas)


def ids_clientes(con: sqlite3.Connection) -> Set[str]:
    return {l["id"] for l in con.execute("SELECT id FROM clientes")}


def codigos_evento(con: sqlite3.Connection) -> Set[str]:
    return {l["codigo"] for l in con.execute("SELECT codigo FROM tipos_evento")}


# ---------------------------------------------------------------------------
# Eventos
# ---------------------------------------------------------------------------
def _gravar_problemas(con: sqlite3.Connection, entidade: str, chave,
                      problemas: Iterable[Problema]) -> None:
    con.executemany(
        "INSERT OR REPLACE INTO problemas_dados (entidade, chave, campo, problema, valor_original) "
        "VALUES (?, ?, ?, ?, ?)",
        [(entidade, str(chave), p.campo, p.problema, p.valor_original) for p in problemas])


def gravar_eventos(con: sqlite3.Connection,
                   lote: Sequence[Tuple[Dict, List[Problema], Dict]],
                   capturado_em: str) -> Dict[str, int]:
    """Insere ou atualiza cada evento do lote. Devolve as contagens.

    - ``novos``: id ainda não existia;
    - ``atualizados``: existia com ``atualizado_em`` mais antigo (ex.: passou
      de ``aberto`` para ``encerrado``);
    - ``inalterados``: existia com o mesmo ``atualizado_em`` (duplicata da API
      ou repetição da fronteira do cursor);
    - ``ignorados``: veio uma versão **mais antiga** do que a gravada. Não pode
      acontecer com a API ordenada, mas protege contra regressão.
    """
    contagem = {"novos": 0, "atualizados": 0, "inalterados": 0, "ignorados": 0, "com_problemas": 0}
    if not lote:
        return contagem

    ids = [ev["id"] for ev, _, _ in lote]
    existentes: Dict[int, str] = {}
    for i in range(0, len(ids), 500):  # limite de parâmetros do SQLite
        fatia = ids[i:i + 500]
        marcas = ",".join("?" * len(fatia))
        for linha in con.execute(
                f"SELECT id, atualizado_em FROM eventos WHERE id IN ({marcas})", fatia):
            existentes[linha["id"]] = linha["atualizado_em"]

    for evento, problemas, bruto in lote:
        anterior = existentes.get(evento["id"])
        if anterior is None:
            contagem["novos"] += 1
        elif evento["atualizado_em"] > anterior:
            contagem["atualizados"] += 1
        elif evento["atualizado_em"] == anterior:
            contagem["inalterados"] += 1
            continue
        else:
            contagem["ignorados"] += 1
            continue

        con.execute(
            "INSERT OR REPLACE INTO eventos "
            "(id, cliente_id, codigo_evento, zona, data_hora, status, operador, "
            " tempo_atendimento_seg, resultado, observacao, atualizado_em, capturado_em, bruto_json) "
            "VALUES (:id, :cliente_id, :codigo_evento, :zona, :data_hora, :status, :operador, "
            " :tempo_atendimento_seg, :resultado, :observacao, :atualizado_em, :capturado_em, :bruto_json)",
            {**evento, "capturado_em": capturado_em,
             "bruto_json": json.dumps(bruto, ensure_ascii=False)})
        # O evento mudou: os problemas da versão anterior não valem mais.
        con.execute("DELETE FROM problemas_dados WHERE entidade = 'evento' AND chave = ?",
                    (str(evento["id"]),))
        if problemas:
            contagem["com_problemas"] += 1
            _gravar_problemas(con, "evento", evento["id"], problemas)
        existentes[evento["id"]] = evento["atualizado_em"]

    return contagem


def gravar_rejeitado(con: sqlite3.Connection, execucao_id: int, bruto: Dict, motivo: str) -> None:
    con.execute(
        "INSERT INTO eventos_rejeitados (execucao_id, motivo, bruto_json) VALUES (?, ?, ?)",
        (execucao_id, motivo, json.dumps(bruto, ensure_ascii=False)))


def completar_operadores(con: sqlite3.Connection) -> int:
    """Troca 'Bruno' por 'Bruno Kessler' quando só existe um operador com esse
    primeiro nome. Roda no fim de cada execução, quando já conhecemos todos os
    nomes completos. Devolve quantas linhas mudaram."""
    nomes = {l["operador"] for l in con.execute(
        "SELECT DISTINCT operador FROM eventos WHERE operador IS NOT NULL")}
    alterados = 0
    for curto, completo in completar_nomes(nomes).items():
        cur = con.execute("UPDATE eventos SET operador = ? WHERE operador = ?", (completo, curto))
        alterados += cur.rowcount
    return alterados
