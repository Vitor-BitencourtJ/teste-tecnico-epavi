"""Cliente HTTP da API da central.

Responsabilidades deste módulo:

- autenticar (cabeçalho ``X-API-Key``);
- respeitar o limite de requisições por segundo;
- tentar de novo em falhas temporárias (429, 5xx, timeout, queda de conexão)
  com espera crescente, para sobreviver à instabilidade da API;
- percorrer todas as páginas de ``/eventos`` sem perder registros, mesmo que a
  lista mude durante a leitura.

Ele devolve os dados exatamente como a API manda. Limpeza é papel de outro módulo.
"""
import logging
import random
import time
from typing import Dict, Iterator, List, Optional

import requests

from . import config

log = logging.getLogger(__name__)


class ErroAPI(Exception):
    """Falha definitiva ao falar com a API (não adianta tentar de novo)."""


class ErroAutenticacao(ErroAPI):
    """A chave de API foi recusada."""


class ClienteCentral:
    def __init__(
        self,
        url_base: str = config.API_URL,
        api_key: str = config.API_KEY,
        timeout: float = config.API_TIMEOUT,
        intervalo_min: float = config.API_INTERVALO_MIN,
        max_tentativas: int = config.API_MAX_TENTATIVAS,
    ):
        self.url_base = url_base.rstrip("/")
        self.timeout = timeout
        self.intervalo_min = intervalo_min
        self.max_tentativas = max_tentativas
        self._sessao = requests.Session()
        self._sessao.headers["X-API-Key"] = api_key
        self._ultima_requisicao = 0.0
        self.total_requisicoes = 0
        self.total_retentativas = 0

    # ------------------------------------------------------------------
    # Requisição básica com retentativa
    # ------------------------------------------------------------------
    def _esperar_vez(self) -> None:
        """Garante um intervalo mínimo entre requisições (limite da API)."""
        falta = self.intervalo_min - (time.monotonic() - self._ultima_requisicao)
        if falta > 0:
            time.sleep(falta)
        self._ultima_requisicao = time.monotonic()

    def get(self, rota: str, params: Optional[Dict] = None) -> Dict:
        """Faz GET em ``rota`` e devolve o JSON. Repete em falhas temporárias."""
        url = f"{self.url_base}{rota}"
        for tentativa in range(1, self.max_tentativas + 1):
            self._esperar_vez()
            self.total_requisicoes += 1
            espera_sugerida = None
            try:
                resposta = self._sessao.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                motivo = f"falha de conexao ({type(exc).__name__})"
            else:
                if resposta.status_code == 200:
                    return resposta.json()
                if resposta.status_code == 401:
                    raise ErroAutenticacao("chave de API recusada (401)")
                if resposta.status_code in (400, 404):
                    raise ErroAPI(f"HTTP {resposta.status_code} em {rota}: {resposta.text[:200]}")
                if resposta.status_code == 429:
                    espera_sugerida = float(resposta.headers.get("Retry-After", 2))
                motivo = f"HTTP {resposta.status_code}"

            if tentativa == self.max_tentativas:
                raise ErroAPI(f"desisti de {rota} apos {tentativa} tentativas ({motivo})")

            # Espera exponencial com um pouco de aleatoriedade, limitada a 30 s.
            # Se a API disse quanto esperar (Retry-After), respeitamos.
            espera = espera_sugerida or min(30.0, 0.5 * 2 ** (tentativa - 1))
            espera += random.uniform(0, 0.5)
            self.total_retentativas += 1
            log.warning("%s em %s (tentativa %d/%d); aguardando %.1fs",
                        motivo, rota, tentativa, self.max_tentativas, espera)
            time.sleep(espera)

        raise ErroAPI("inalcancavel")  # o laço sempre retorna ou levanta antes

    # ------------------------------------------------------------------
    # Endpoints
    # ------------------------------------------------------------------
    def saude(self) -> Dict:
        return self.get("/api/v1/saude")

    def clientes(self) -> List[Dict]:
        return self.get("/api/v1/clientes")["dados"]

    def tipos_evento(self) -> List[Dict]:
        return self.get("/api/v1/tipos-evento")["dados"]

    def pagina_eventos(self, pagina: int, por_pagina: int,
                       atualizado_desde: Optional[str] = None) -> Dict:
        params = {"pagina": pagina, "por_pagina": por_pagina}
        if atualizado_desde:
            params["atualizado_desde"] = atualizado_desde
        return self.get("/api/v1/eventos", params)

    def eventos(self, atualizado_desde: Optional[str] = None,
                por_pagina: int = config.API_POR_PAGINA) -> Iterator[List[Dict]]:
        """Percorre todos os eventos, uma página por vez.

        A API ordena por ``atualizado_em``. Como eventos mudam enquanto lemos
        (um ``aberto`` vira ``em_atendimento`` e pula para o fim da lista), a
        posição de todo o resto muda e a paginação por número de página pode
        pular registros. Por isso avançamos por **cursor**: a cada página,
        pedimos de novo a partir do último ``atualizado_em`` lido. O ``>=`` da
        API faz os registros na fronteira virem repetidos, o que é inofensivo
        porque o banco grava por ``id``.

        Só avançamos o número da página quando uma página inteira tem o mesmo
        ``atualizado_em`` do cursor (não teria como avançar o cursor nela).
        """
        cursor = atualizado_desde
        pagina = 1
        while True:
            resposta = self.pagina_eventos(pagina, por_pagina, cursor)
            dados = resposta["dados"]
            if not dados:
                return
            yield dados
            if pagina >= resposta["total_paginas"]:
                return
            ultimo = dados[-1]["atualizado_em"]
            if cursor is None or ultimo > cursor:
                cursor, pagina = ultimo, 1
            else:
                pagina += 1
