"""Testes da gravação: rodar duas vezes não duplica, versão nova atualiza, antiga é ignorada."""
import sqlite3

from central import banco
from central.normalizacao import Problema


def conexao():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(banco.ESQUEMA)
    return con


def evento(**campos):
    base = {
        "id": 1, "cliente_id": "CLI-0001", "codigo_evento": "E130", "zona": 1,
        "data_hora": "2026-10-13 07:00:00", "status": "aberto", "operador": None,
        "tempo_atendimento_seg": None, "resultado": None, "observacao": None,
        "atualizado_em": "2026-10-13T10:00:00Z",
    }
    base.update(campos)
    return base


def total(con):
    return con.execute("SELECT COUNT(*) FROM eventos").fetchone()[0]


def test_mesmo_evento_duas_vezes_nao_duplica():
    con = conexao()
    lote = [(evento(), [], {}), (evento(), [], {})]  # duplicata exata, como a API manda
    contagem = banco.gravar_eventos(con, lote, "t1")
    assert (contagem["novos"], contagem["inalterados"]) == (1, 1)

    contagem = banco.gravar_eventos(con, lote, "t2")  # segunda execucao
    assert (contagem["novos"], contagem["inalterados"]) == (0, 2)
    assert total(con) == 1


def test_versao_nova_atualiza_e_versao_antiga_e_ignorada():
    con = conexao()
    aberto = (evento(status="aberto", atualizado_em="2026-10-13T10:00:00Z"), [], {})
    encerrado = (evento(status="encerrado", operador="Bruno Kessler", tempo_atendimento_seg=120,
                        atualizado_em="2026-10-13T10:05:00Z"), [], {})

    banco.gravar_eventos(con, [aberto], "t1")
    contagem = banco.gravar_eventos(con, [encerrado], "t2")
    assert contagem["atualizados"] == 1
    linha = con.execute("SELECT status, tempo_atendimento_seg FROM eventos WHERE id = 1").fetchone()
    assert tuple(linha) == ("encerrado", 120)

    contagem = banco.gravar_eventos(con, [aberto], "t3")  # versao velha chegando atrasada
    assert contagem["ignorados"] == 1
    assert con.execute("SELECT status FROM eventos WHERE id = 1").fetchone()[0] == "encerrado"
    assert total(con) == 1


def test_problemas_acompanham_a_versao_gravada():
    con = conexao()
    problema = Problema("status", "status_grafia", "ABERTO")
    banco.gravar_eventos(con, [(evento(), [problema], {})], "t1")
    assert con.execute("SELECT COUNT(*) FROM problemas_dados").fetchone()[0] == 1

    # a versao nova veio limpa: o problema antigo nao vale mais
    banco.gravar_eventos(con, [(evento(status="encerrado", atualizado_em="2026-10-13T10:05:00Z"),
                                [], {})], "t2")
    assert con.execute("SELECT COUNT(*) FROM problemas_dados").fetchone()[0] == 0


def test_bruto_json_e_guardado():
    con = conexao()
    banco.gravar_eventos(con, [(evento(), [], {"id": 1, "status": "ABERTO"})], "t1")
    bruto = con.execute("SELECT bruto_json FROM eventos WHERE id = 1").fetchone()[0]
    assert '"status": "ABERTO"' in bruto


def test_completar_operadores_so_quando_unico():
    con = conexao()
    lote = [(evento(id=1, operador="Bruno Kessler"), [], {}),
            (evento(id=2, operador="Bruno"), [], {}),
            (evento(id=3, operador="Carla Mendes"), [], {}),
            (evento(id=4, operador="Carla Souza"), [], {}),
            (evento(id=5, operador="Carla"), [], {})]
    banco.gravar_eventos(con, lote, "t1")
    assert banco.completar_operadores(con) == 1
    nomes = [l[0] for l in con.execute("SELECT operador FROM eventos ORDER BY id")]
    assert nomes == ["Bruno Kessler", "Bruno Kessler", "Carla Mendes", "Carla Souza", "Carla"]


def test_marca_dagua_sobrevive_a_execucao_com_erro():
    con = conexao()
    execucao = banco.iniciar_execucao(con, "2026-10-13T10:00:00Z", "completa", None)
    banco.atualizar_execucao(con, execucao, marca_dagua="2026-10-13T09:00:00Z", status="erro")
    assert banco.ultima_marca_dagua(con) == "2026-10-13T09:00:00Z"
