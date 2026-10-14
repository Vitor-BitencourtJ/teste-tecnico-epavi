"""Limpeza e padronização dos dados que chegam da API.

Cada função recebe um registro **como veio** e devolve dois valores:

1. o registro limpo, pronto para o banco;
2. a lista de ``Problema`` encontrados, com o valor original, para que nada
   seja corrigido em silêncio. Esses problemas vão para a tabela
   ``problemas_dados`` e aparecem no painel.

Regra geral: corrigimos o que dá para corrigir com segurança (caixa, espaços,
formato de data, número como texto, sinônimos) e **anulamos** o que não dá
para confiar (tempo negativo). Nunca inventamos valor.
"""
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Set, Tuple

TZ_BR = timezone(timedelta(hours=-3))
FORMATO_DATA_BANCO = "%Y-%m-%d %H:%M:%S"  # horário de Brasília, sem fuso

STATUS_VALIDOS = {"aberto", "em_atendimento", "encerrado", "registrado"}
STATUS_SINONIMOS = {"fechado": "encerrado"}

# Abreviações de cidade que a regra genérica (sem acento, minúsculas) não resolve.
CIDADE_APELIDOS = {"poa": "porto alegre", "s. leopoldo": "sao leopoldo"}
PALAVRAS_MINUSCULAS = {"de", "da", "do", "das", "dos", "e"}


@dataclass(frozen=True)
class Problema:
    campo: str
    problema: str
    valor_original: Optional[str]


class DadoInvalido(ValueError):
    """O registro não pode ser aproveitado nem com correção."""


# ---------------------------------------------------------------------------
# Auxiliares de texto
# ---------------------------------------------------------------------------
def _sem_acentos(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def _espacos(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip()


def _titulo(texto: str) -> str:
    """'INDUSTRIA DE PLASTICOS LTDA' -> 'Industria de Plasticos Ltda'."""
    palavras = []
    for i, p in enumerate(texto.lower().split(" ")):
        palavras.append(p if (i > 0 and p in PALAVRAS_MINUSCULAS) else p.capitalize())
    return " ".join(palavras)


def _texto(valor) -> Optional[str]:
    if valor is None:
        return None
    valor = str(valor)
    return valor if valor.strip() else None


# ---------------------------------------------------------------------------
# Clientes
# ---------------------------------------------------------------------------
def normalizar_cidade(valor: str) -> str:
    chave = _sem_acentos(_espacos(valor)).lower()
    chave = CIDADE_APELIDOS.get(chave, chave)
    return _titulo(chave)


def normalizar_cliente(bruto: Dict) -> Tuple[Dict, List[Problema]]:
    problemas: List[Problema] = []

    cidade = normalizar_cidade(bruto["cidade"])
    if cidade != bruto["cidade"]:
        problemas.append(Problema("cidade", "cidade_grafia", bruto["cidade"]))

    nome = _espacos(bruto["nome"])
    if nome.isupper():
        problemas.append(Problema("nome", "nome_caixa_alta", bruto["nome"]))
        nome = _titulo(nome)

    limpo = {
        "id": bruto["id"].strip().upper(),
        "nome": nome,
        "tipo": bruto["tipo"],
        "cidade": cidade,
        "plano": bruto["plano"],
        "inicio_contrato": bruto["inicio_contrato"],
        "ativo": 1 if bruto["ativo"] else 0,
        "data_cancelamento": bruto["data_cancelamento"],
    }
    return limpo, problemas


# ---------------------------------------------------------------------------
# Eventos
# ---------------------------------------------------------------------------
def _parse_data_hora(valor) -> Tuple[str, Optional[str]]:
    """Devolve (data no formato do banco, nome do problema ou None).

    Aceita ISO 8601 com fuso (padrão da API) e ``dd/mm/aaaa hh:mm:ss``, que a
    central manda sem fuso. Conferimos nos dados que esse segundo formato está
    em horário de Brasília: ``data_hora`` + tempo de atendimento bate com o
    ``atualizado_em`` em UTC.
    """
    if not isinstance(valor, str) or not valor.strip():
        raise DadoInvalido(f"data_hora vazia: {valor!r}")
    texto = valor.strip()
    try:
        dt = datetime.fromisoformat(texto.replace("Z", "+00:00"))
        problema = None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ_BR)
            problema = "data_hora_sem_fuso"
    except ValueError:
        try:
            dt = datetime.strptime(texto, "%d/%m/%Y %H:%M:%S").replace(tzinfo=TZ_BR)
            problema = "data_hora_formato_br"
        except ValueError:
            raise DadoInvalido(f"data_hora irreconhecivel: {valor!r}") from None
    return dt.astimezone(TZ_BR).strftime(FORMATO_DATA_BANCO), problema


def _parse_tempo(valor, status: str, problemas: List[Problema]) -> Optional[int]:
    if valor is None:
        if status == "encerrado":
            problemas.append(Problema("tempo_atendimento_seg", "tempo_ausente", None))
        return None
    if isinstance(valor, str):
        problemas.append(Problema("tempo_atendimento_seg", "tempo_texto", valor))
        try:
            valor = int(valor.strip())
        except ValueError:
            raise DadoInvalido(f"tempo_atendimento_seg irreconhecivel: {valor!r}") from None
    if valor < 0:
        # Não dá para saber se foi só o sinal que inverteu. Melhor não ter o
        # número do que ter um número errado na média.
        problemas.append(Problema("tempo_atendimento_seg", "tempo_negativo", str(valor)))
        return None
    return int(valor)


def _parse_zona(valor) -> Optional[int]:
    if valor is None or valor == "":
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        raise DadoInvalido(f"zona irreconhecivel: {valor!r}") from None


def normalizar_evento(bruto: Dict, codigos_conhecidos: Set[str],
                      clientes_conhecidos: Set[str]) -> Tuple[Dict, List[Problema]]:
    problemas: List[Problema] = []

    try:
        id_evento = int(bruto["id"])
    except (KeyError, TypeError, ValueError):
        raise DadoInvalido(f"id invalido: {bruto.get('id')!r}") from None

    # --- cliente -----------------------------------------------------------
    cliente_id = _espacos(str(bruto.get("cliente_id") or "")).upper()
    if not cliente_id:
        raise DadoInvalido("cliente_id vazio")
    if cliente_id != bruto["cliente_id"]:
        problemas.append(Problema("cliente_id", "cliente_id_grafia", bruto["cliente_id"]))
    if cliente_id not in clientes_conhecidos:
        problemas.append(Problema("cliente_id", "cliente_desconhecido", bruto["cliente_id"]))

    # --- código do evento ---------------------------------------------------
    codigo = _espacos(str(bruto.get("codigo_evento") or "")).upper()
    if not codigo:
        raise DadoInvalido("codigo_evento vazio")
    if codigo != bruto["codigo_evento"]:
        problemas.append(Problema("codigo_evento", "codigo_evento_grafia", bruto["codigo_evento"]))
    if codigo not in codigos_conhecidos:
        problemas.append(Problema("codigo_evento", "codigo_evento_desconhecido", bruto["codigo_evento"]))

    # --- status --------------------------------------------------------------
    status = _espacos(str(bruto.get("status") or "")).lower()
    if status != bruto["status"]:
        problemas.append(Problema("status", "status_grafia", bruto["status"]))
    if status in STATUS_SINONIMOS:
        problemas.append(Problema("status", "status_sinonimo", bruto["status"]))
        status = STATUS_SINONIMOS[status]
    if status not in STATUS_VALIDOS:
        raise DadoInvalido(f"status desconhecido: {bruto['status']!r}")

    # --- data ------------------------------------------------------------------
    data_hora, problema_data = _parse_data_hora(bruto.get("data_hora"))
    if problema_data:
        problemas.append(Problema("data_hora", problema_data, bruto["data_hora"]))

    # --- operador -------------------------------------------------------------
    operador = _texto(bruto.get("operador"))
    if operador is not None:
        limpo = _titulo(_espacos(operador))
        if limpo != operador:
            problemas.append(Problema("operador", "operador_grafia", operador))
        if " " not in limpo:
            # Só o primeiro nome. É completado no fim da execução, quando
            # conhecemos todos os nomes completos (ver banco.completar_operadores).
            problemas.append(Problema("operador", "operador_nome_incompleto", operador))
        operador = limpo

    tempo = _parse_tempo(bruto.get("tempo_atendimento_seg"), status, problemas)

    limpo = {
        "id": id_evento,
        "cliente_id": cliente_id,
        "codigo_evento": codigo,
        "zona": _parse_zona(bruto.get("zona")),
        "data_hora": data_hora,
        "status": status,
        "operador": operador,
        "tempo_atendimento_seg": tempo,
        "resultado": _texto(bruto.get("resultado")),
        "observacao": _texto(bruto.get("observacao")),
        "atualizado_em": bruto["atualizado_em"],
    }
    return limpo, problemas


def completar_nomes(nomes: Iterable[str]) -> Dict[str, str]:
    """Mapeia primeiro-nome -> nome completo quando a correspondência é única.

    ``{'Bruno Kessler', 'Bruno', 'Diego Ramos'}`` -> ``{'Bruno': 'Bruno Kessler'}``.
    Se dois operadores tiverem o mesmo primeiro nome, o incompleto fica como está.
    """
    completos = {n for n in nomes if " " in n}
    mapa: Dict[str, str] = {}
    for curto in {n for n in nomes if " " not in n}:
        candidatos = {c for c in completos if c.split(" ")[0] == curto}
        if len(candidatos) == 1:
            mapa[curto] = candidatos.pop()
    return mapa
