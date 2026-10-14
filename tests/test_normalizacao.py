"""Testes da limpeza. Cada caso reproduz um problema visto nos dados da API."""
import pytest

from central.normalizacao import (DadoInvalido, completar_nomes, normalizar_cidade,
                                  normalizar_cliente, normalizar_evento)

CODIGOS = {"E130", "E602", "R401"}
CLIENTES = {"CLI-0001", "CLI-0028"}


def evento(**campos):
    base = {
        "id": 100009, "cliente_id": "CLI-0001", "codigo_evento": "E130", "zona": 3,
        "data_hora": "2026-07-15T03:40:58-03:00", "status": "encerrado",
        "operador": "Bruno Kessler", "tempo_atendimento_seg": 226, "resultado": "falso_alarme",
        "observacao": None, "atualizado_em": "2026-07-15T06:45:22Z",
    }
    base.update(campos)
    return base


def problemas_de(lista):
    return {p.problema for p in lista}


def test_evento_limpo_nao_gera_problema():
    limpo, problemas = normalizar_evento(evento(), CODIGOS, CLIENTES)
    assert problemas == []
    assert limpo["data_hora"] == "2026-07-15 03:40:58"
    assert limpo["tempo_atendimento_seg"] == 226


def test_data_formato_brasileiro_e_horario_de_brasilia():
    limpo, problemas = normalizar_evento(evento(data_hora="15/07/2026 03:40:58"), CODIGOS, CLIENTES)
    assert limpo["data_hora"] == "2026-07-15 03:40:58"
    assert problemas_de(problemas) == {"data_hora_formato_br"}


def test_data_iso_em_utc_vira_horario_local():
    limpo, _ = normalizar_evento(evento(data_hora="2026-07-15T06:40:58Z"), CODIGOS, CLIENTES)
    assert limpo["data_hora"] == "2026-07-15 03:40:58"


def test_data_irreconhecivel_rejeita():
    with pytest.raises(DadoInvalido):
        normalizar_evento(evento(data_hora="ontem"), CODIGOS, CLIENTES)


@pytest.mark.parametrize("sujo", ["e130", "E130 ", " e130"])
def test_codigo_evento_grafia(sujo):
    limpo, problemas = normalizar_evento(evento(codigo_evento=sujo), CODIGOS, CLIENTES)
    assert limpo["codigo_evento"] == "E130"
    assert problemas_de(problemas) == {"codigo_evento_grafia"}


def test_codigo_desconhecido_e_mantido_e_marcado():
    limpo, problemas = normalizar_evento(evento(codigo_evento="E999"), CODIGOS, CLIENTES)
    assert limpo["codigo_evento"] == "E999"
    assert problemas_de(problemas) == {"codigo_evento_desconhecido"}


@pytest.mark.parametrize("sujo", ["ENCERRADO", "Encerrado"])
def test_status_grafia(sujo):
    limpo, problemas = normalizar_evento(evento(status=sujo), CODIGOS, CLIENTES)
    assert limpo["status"] == "encerrado"
    assert problemas_de(problemas) == {"status_grafia"}


def test_status_fechado_e_sinonimo_de_encerrado():
    limpo, problemas = normalizar_evento(evento(status="fechado"), CODIGOS, CLIENTES)
    assert limpo["status"] == "encerrado"
    assert problemas_de(problemas) == {"status_sinonimo"}


def test_status_desconhecido_rejeita():
    with pytest.raises(DadoInvalido):
        normalizar_evento(evento(status="cancelado"), CODIGOS, CLIENTES)


@pytest.mark.parametrize("sujo", ["BRUNO KESSLER", "Bruno Kessler  ", "bruno kessler"])
def test_operador_grafia(sujo):
    limpo, problemas = normalizar_evento(evento(operador=sujo), CODIGOS, CLIENTES)
    assert limpo["operador"] == "Bruno Kessler"
    assert problemas_de(problemas) == {"operador_grafia"}


def test_operador_so_primeiro_nome_e_marcado():
    limpo, problemas = normalizar_evento(evento(operador="Bruno"), CODIGOS, CLIENTES)
    assert limpo["operador"] == "Bruno"
    assert problemas_de(problemas) == {"operador_nome_incompleto"}


def test_completar_nomes_so_quando_unico():
    nomes = {"Bruno Kessler", "Bruno", "Diego Ramos", "Carla Mendes", "Carla Souza", "Carla"}
    assert completar_nomes(nomes) == {"Bruno": "Bruno Kessler"}


def test_tempo_como_texto_vira_inteiro():
    limpo, problemas = normalizar_evento(evento(tempo_atendimento_seg="226"), CODIGOS, CLIENTES)
    assert limpo["tempo_atendimento_seg"] == 226
    assert problemas_de(problemas) == {"tempo_texto"}


def test_tempo_negativo_vira_nulo():
    limpo, problemas = normalizar_evento(evento(tempo_atendimento_seg=-226), CODIGOS, CLIENTES)
    assert limpo["tempo_atendimento_seg"] is None
    assert problemas_de(problemas) == {"tempo_negativo"}


def test_tempo_ausente_em_encerrado_e_marcado():
    limpo, problemas = normalizar_evento(evento(tempo_atendimento_seg=None), CODIGOS, CLIENTES)
    assert limpo["tempo_atendimento_seg"] is None
    assert problemas_de(problemas) == {"tempo_ausente"}


def test_tempo_ausente_em_registrado_e_normal():
    ev = evento(codigo_evento="E602", status="registrado", operador=None,
                tempo_atendimento_seg=None, resultado=None, zona=None)
    _, problemas = normalizar_evento(ev, CODIGOS, CLIENTES)
    assert problemas == []


def test_cliente_id_minusculo():
    limpo, problemas = normalizar_evento(evento(cliente_id="cli-0028"), CODIGOS, CLIENTES)
    assert limpo["cliente_id"] == "CLI-0028"
    assert problemas_de(problemas) == {"cliente_id_grafia"}


@pytest.mark.parametrize("sujo", ["CLI-9999", "CLI-0000"])
def test_cliente_desconhecido_e_mantido_e_marcado(sujo):
    limpo, problemas = normalizar_evento(evento(cliente_id=sujo), CODIGOS, CLIENTES)
    assert limpo["cliente_id"] == sujo
    assert problemas_de(problemas) == {"cliente_desconhecido"}


def test_varios_problemas_no_mesmo_evento():
    ev = evento(codigo_evento="e130", status="fechado", data_hora="15/07/2026 03:40:58",
                tempo_atendimento_seg="-5")
    limpo, problemas = normalizar_evento(ev, CODIGOS, CLIENTES)
    assert limpo["tempo_atendimento_seg"] is None
    assert problemas_de(problemas) == {"codigo_evento_grafia", "status_sinonimo",
                                       "data_hora_formato_br", "tempo_texto", "tempo_negativo"}


@pytest.mark.parametrize("sujo,esperado", [
    ("POA", "Porto Alegre"), ("porto alegre", "Porto Alegre"), ("Porto Alegre ", "Porto Alegre"),
    ("São Leopoldo", "Sao Leopoldo"), ("S. Leopoldo", "Sao Leopoldo"),
    ("Gravataí", "Gravatai"), ("GRAVATAI", "Gravatai"), ("Viamão", "Viamao"),
    (" Canoas", "Canoas"), ("CANOAS", "Canoas"), ("Novo Hamburgo", "Novo Hamburgo"),
])
def test_normalizar_cidade(sujo, esperado):
    assert normalizar_cidade(sujo) == esperado


def test_cliente_nome_caixa_alta():
    bruto = {"id": "CLI-0003", "nome": "INDUSTRIA DE PLASTICOS HORIZONTE LTDA", "tipo": "industrial",
             "cidade": "POA", "plano": "Plus", "inicio_contrato": "2020-01-01",
             "ativo": True, "data_cancelamento": None}
    limpo, problemas = normalizar_cliente(bruto)
    assert limpo["nome"] == "Industria de Plasticos Horizonte Ltda"
    assert limpo["cidade"] == "Porto Alegre"
    assert limpo["ativo"] == 1
    assert problemas_de(problemas) == {"nome_caixa_alta", "cidade_grafia"}
