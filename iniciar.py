"""Sobe a captura contínua e o painel com um só comando.

    python iniciar.py                    # captura a cada 2 min + painel em http://127.0.0.1:8050
    python iniciar.py --intervalo 300    # captura a cada 5 min
    python iniciar.py --porta 9000
    python iniciar.py --recriar          # apaga o banco e captura tudo de novo antes de subir

A API da central (no teste, a API mock) é um sistema externo e roda à parte:
    python api_mock/mock_api.py

Captura e painel continuam sendo processos separados: se a captura falhar por
instabilidade da API, ela tenta de novo na rodada seguinte e o painel segue no
ar mostrando o último dado. Este script só os inicia juntos e fecha os dois no
Ctrl+C. Em produção, prefira o agendador do sistema (ver README).
"""
import argparse
import subprocess
import sys
import time

import requests

from central import config

RAIZ = config.RAIZ


def api_no_ar() -> bool:
    try:
        return requests.get(f"{config.API_URL.rstrip('/')}/api/v1/saude", timeout=5).ok
    except requests.RequestException:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Inicia a captura contínua e o painel.")
    parser.add_argument("--intervalo", type=int, default=120, metavar="SEGUNDOS",
                        help="intervalo entre capturas (padrão: 120)")
    parser.add_argument("--porta", type=int, default=8050, help="porta do painel (padrão: 8050)")
    parser.add_argument("--recriar", action="store_true",
                        help="apaga o banco e faz uma captura completa antes de subir")
    args = parser.parse_args()

    if not config.API_KEY:
        print("CENTRAL_API_KEY não definida. Copie .env.example para .env e preencha a chave.")
        return 2
    if not api_no_ar():
        print(f"Aviso: a API não respondeu em {config.API_URL}. Suba-a com "
              "`python api_mock/mock_api.py`; a captura tenta de novo a cada rodada.")

    # Sem banco (ou com --recriar), faz a captura completa antes de abrir o painel,
    # para ele não abrir vazio.
    if args.recriar or not config.CAMINHO_BANCO.exists():
        print("Capturando o histórico completo antes de abrir o painel...")
        comando = [sys.executable, "capturar.py"] + (["--recriar"] if args.recriar else [])
        if subprocess.run(comando, cwd=RAIZ).returncode == 2:
            return 2

    processos = {
        "captura": subprocess.Popen([sys.executable, "capturar.py", "--a-cada", str(args.intervalo)], cwd=RAIZ),
        "painel": subprocess.Popen([sys.executable, "painel.py", "--porta", str(args.porta)], cwd=RAIZ),
    }
    print(f"\nPainel em http://127.0.0.1:{args.porta}  |  modo monitoramento em "
          f"http://127.0.0.1:{args.porta}/monitoramento")
    print(f"Captura a cada {args.intervalo} s. Ctrl+C para parar tudo.\n")

    codigo = 0
    try:
        while True:
            for nome, proc in processos.items():
                if proc.poll() is not None:
                    print(f"\nO processo '{nome}' terminou (código {proc.returncode}). Encerrando o resto.")
                    if nome == "captura" and proc.returncode == 2:
                        print("A API passou a servir outro histórico (foi reiniciada em outro dia). "
                              "Rode `python iniciar.py --recriar` para começar um banco novo.")
                    codigo = proc.returncode or 1
                    raise KeyboardInterrupt
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for proc in processos.values():
            if proc.poll() is None:
                proc.terminate()
        for proc in processos.values():
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        print("Captura e painel encerrados.")
    return codigo


if __name__ == "__main__":
    sys.exit(main())
