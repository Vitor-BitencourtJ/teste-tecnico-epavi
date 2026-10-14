"""Ponto de entrada da captura.

    python capturar.py                 # uma rodada (completa na 1a vez, incremental depois)
    python capturar.py --a-cada 300    # fica rodando, uma rodada a cada 5 minutos
    python capturar.py --recriar       # apaga o banco e captura tudo de novo
    python capturar.py --verboso       # mostra o progresso pagina a pagina

Os logs vao para o console e para logs/captura_AAAA-MM-DD.log.
"""
import argparse
import logging
import sys
import time
from datetime import date

from central import banco, captura, config
from central.api import ClienteCentral, ErroAPI

log = logging.getLogger("capturar")


def configurar_logs(verboso: bool) -> None:
    config.PASTA_LOGS.mkdir(parents=True, exist_ok=True)
    arquivo = config.PASTA_LOGS / f"captura_{date.today().isoformat()}.log"
    logging.basicConfig(
        level=logging.DEBUG if verboso else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(arquivo, encoding="utf-8")],
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def rodar_uma_vez() -> int:
    """Devolve o codigo de saida: 0 ok, 1 falha temporaria, 2 precisa de decisao humana."""
    con = banco.conectar(config.CAMINHO_BANCO)
    try:
        captura.executar(con, ClienteCentral())
        return 0
    except captura.ReinicioAPI as exc:
        log.error("captura interrompida: %s", exc)
        return 2
    except ErroAPI as exc:
        log.error("API indisponivel: %s. O que foi gravado ate aqui esta salvo; "
                  "a proxima rodada continua do mesmo ponto.", exc)
        return 1
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Captura eventos da central para o banco local.")
    parser.add_argument("--a-cada", type=int, metavar="SEGUNDOS",
                        help="repete a captura nesse intervalo, sem parar")
    parser.add_argument("--recriar", action="store_true", help="apaga o banco antes de comecar")
    parser.add_argument("--verboso", action="store_true")
    args = parser.parse_args()

    configurar_logs(args.verboso)
    if not config.API_KEY:
        log.error("CENTRAL_API_KEY nao definida. Copie .env.example para .env e preencha a chave.")
        return 2
    if args.recriar:
        banco.apagar(config.CAMINHO_BANCO)
        log.info("banco %s apagado", config.CAMINHO_BANCO)

    if not args.a_cada:
        return rodar_uma_vez()

    log.info("modo continuo: uma rodada a cada %d s (Ctrl+C para parar)", args.a_cada)
    while True:
        inicio = time.monotonic()
        if rodar_uma_vez() == 2:
            return 2
        espera = max(0.0, args.a_cada - (time.monotonic() - inicio))
        try:
            time.sleep(espera)
        except KeyboardInterrupt:
            log.info("encerrado pelo usuario")
            return 0


if __name__ == "__main__":
    sys.exit(main())
