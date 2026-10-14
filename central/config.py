"""Configuração do projeto.

Os valores vêm de variáveis de ambiente, lidas também do arquivo ``.env`` na
raiz (copie ``.env.example`` para ``.env``). O ``.env`` não vai para o git.

A chave da API é o único valor sem padrão: não fica escrita no código. O resto
tem um padrão que funciona com a API mock rodando localmente.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")  # variáveis já definidas no ambiente têm prioridade

API_URL = os.environ.get("CENTRAL_API_URL", "http://127.0.0.1:8000")
API_KEY = os.environ.get("CENTRAL_API_KEY", "")

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

# De quantos em quantos segundos o painel e o modo monitoramento recarregam os dados.
# O iniciar.py ajusta para o mesmo valor do intervalo de captura.
PAINEL_ATUALIZAR_SEG = int(os.environ.get("CENTRAL_PAINEL_ATUALIZAR_SEG", "120"))
