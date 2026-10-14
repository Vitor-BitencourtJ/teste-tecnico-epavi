"""Sobe o painel web.

    python painel.py                  # http://127.0.0.1:8050
    python painel.py --porta 9000

Precisa do banco gerado pela captura (python capturar.py).
"""
import argparse
import logging

from painel.app import criar_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Painel da central de monitoramento.")
    parser.add_argument("--porta", type=int, default=8050)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--debug", action="store_true", help="recarrega ao editar os arquivos")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    print(f"Painel em http://{args.host}:{args.porta}  (Ctrl+C para parar)")
    criar_app().run(host=args.host, port=args.porta, debug=args.debug)


if __name__ == "__main__":
    main()
