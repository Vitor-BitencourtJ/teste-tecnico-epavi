"""Configuração do projeto.

Tudo tem um valor padrão que funciona com a API mock rodando localmente.
Qualquer valor pode ser sobrescrito por variável de ambiente, para não
precisar mexer no código ao apontar para outro servidor.
"""
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

API_URL = os.environ.get("CENTRAL_API_URL", "http://127.0.0.1:8000")
API_KEY = os.environ.get("CENTRAL_API_KEY", "epavi-teste-2026")

# Segundos de espera por resposta. A API mock às vezes demora 6 s de
# propósito, então o timeout precisa ser folgado em relação a isso.
API_TIMEOUT = float(os.environ.get("CENTRAL_API_TIMEOUT", "30"))

# A API aceita 5 req/s. Trabalhamos abaixo disso para quase nunca receber 429.
API_INTERVALO_MIN = float(os.environ.get("CENTRAL_API_INTERVALO_MIN", "0.25"))
API_MAX_TENTATIVAS = int(os.environ.get("CENTRAL_API_MAX_TENTATIVAS", "8"))

# Máximo permitido pela API. Menos requisições, menos chance de falhar no meio.
API_POR_PAGINA = int(os.environ.get("CENTRAL_API_POR_PAGINA", "200"))

CAMINHO_BANCO = Path(os.environ.get("CENTRAL_BANCO", RAIZ / "dados" / "central.db"))
PASTA_LOGS = Path(os.environ.get("CENTRAL_LOGS", RAIZ / "logs"))
