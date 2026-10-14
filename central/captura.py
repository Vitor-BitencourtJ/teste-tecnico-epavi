"""Orquestra uma rodada de captura: API -> limpeza -> banco.

Fluxo de ``executar``:

1. Consulta ``/saude`` e confere se a API ainda serve a mesma janela de
   histórico gravada no banco (ver ``ReinicioAPI``).
2. Descobre a marca d'água da última rodada. Sem marca: captura completa.
   Com marca: pede só ``atualizado_desde`` a marca (incremental).
3. Atualiza os catálogos (tipos de evento e clientes).
4. Percorre as páginas de eventos. Cada página é limpa, gravada e
   confirmada (``commit``) antes de pedir a próxima, junto com a marca
   d'água até ali. Se a API cair no meio, nada do que já foi gravado se
   perde e a próxima rodada continua de onde parou.
5. Completa nomes de operador que vieram só com o primeiro nome.
"""
import logging
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from typing import Dict

from . import banco
from .api import ClienteCentral
from .normalizacao import DadoInvalido, normalizar_cliente, normalizar_evento

log = logging.getLogger(__name__)

CHAVE_HISTORICO = "api_historico_inicio"


class ReinicioAPI(RuntimeError):
    """A API passou a servir outra janela de histórico; os ids não são mais os mesmos."""


def _agora() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def verificar_janela_historico(con: sqlite3.Connection, saude: Dict) -> None:
    """A API mock renumera todos os eventos quando é reiniciada em outro dia.
    Se gravássemos por cima, o id 100001 passaria a ser outro evento. Então
    comparamos a janela e paramos se ela mudou."""
    atual = saude.get("historico_inicio")
    gravado = banco.ler_metadado(con, CHAVE_HISTORICO)
    if gravado and atual and gravado != atual:
        raise ReinicioAPI(
            f"a API mudou a janela de historico ({gravado} -> {atual}); os ids nao sao mais "
            "os mesmos. Rode com --recriar para comecar um banco novo.")
    if atual and not gravado:
        banco.gravar_metadado(con, CHAVE_HISTORICO, atual)


def executar(con: sqlite3.Connection, api: ClienteCentral) -> Dict[str, int]:
    saude = api.saude()
    verificar_janela_historico(con, saude)

    marca = banco.ultima_marca_dagua(con)
    modo = "incremental" if marca else "completa"
    execucao_id = banco.iniciar_execucao(con, _agora(), modo, marca)
    con.commit()
    log.info("execucao %d (%s) iniciada; atualizado_desde=%s", execucao_id, modo, marca)

    stats: Counter = Counter()
    try:
        tipos = api.tipos_evento()
        banco.gravar_tipos_evento(con, tipos)
        clientes = [normalizar_cliente(c) for c in api.clientes()]
        banco.gravar_clientes(con, clientes)
        con.commit()
        log.info("catalogos: %d tipos de evento, %d clientes (%d com correcao)",
                 len(tipos), len(clientes), sum(1 for _, p in clientes if p))

        codigos = banco.codigos_evento(con)
        ids_clientes = banco.ids_clientes(con)
        capturado_em = _agora()
        marca_nova = marca

        for numero, pagina in enumerate(api.eventos(marca), start=1):
            stats["registros_lidos"] += len(pagina)
            lote = []
            for bruto in pagina:
                try:
                    lote.append((*normalizar_evento(bruto, codigos, ids_clientes), bruto))
                except DadoInvalido as exc:
                    stats["rejeitados"] += 1
                    banco.gravar_rejeitado(con, execucao_id, bruto, str(exc))
                    log.warning("evento rejeitado: %s | %s", exc, bruto)

            stats.update(banco.gravar_eventos(con, lote, capturado_em))
            marca_nova = max(marca_nova or "", pagina[-1]["atualizado_em"])
            banco.atualizar_execucao(con, execucao_id, marca_dagua=marca_nova, **stats)
            con.commit()
            log.debug("pagina %d: %d registros, marca %s", numero, len(pagina), marca_nova)

        completados = banco.completar_operadores(con)
        if completados:
            log.info("%d eventos tiveram o nome do operador completado", completados)

        banco.atualizar_execucao(
            con, execucao_id, status="ok", fim=_agora(), marca_dagua=marca_nova,
            requisicoes=api.total_requisicoes, retentativas=api.total_retentativas, **stats)
        con.commit()
    except Exception as exc:
        banco.atualizar_execucao(
            con, execucao_id, status="erro", fim=_agora(), erro=f"{type(exc).__name__}: {exc}",
            requisicoes=api.total_requisicoes, retentativas=api.total_retentativas, **stats)
        con.commit()
        raise

    log.info("execucao %d concluida: %d lidos | %d novos | %d atualizados | %d inalterados | "
             "%d ignorados | %d rejeitados | %d com correcao | %d requisicoes (%d retentativas)",
             execucao_id, stats["registros_lidos"], stats["novos"], stats["atualizados"],
             stats["inalterados"], stats["ignorados"], stats["rejeitados"], stats["com_problemas"],
             api.total_requisicoes, api.total_retentativas)
    return dict(stats)
