# API da Central de Monitoramento (mock)

Esta API simula a central que recebe os eventos dos painéis de alarme dos clientes. **Todos os dados são fictícios.**

## Como rodar

Você só precisa do Python 3.8 ou mais novo. A API usa apenas a biblioteca padrão, então não há nada para instalar.

```bash
python mock_api.py                # http://127.0.0.1:8000
python mock_api.py --porta 9000   # outra porta
python mock_api.py --silencioso   # não imprime cada requisição
```

Cada vez que a API sobe, ela traz:

- **Histórico:** os 90 dias anteriores à data de hoje.
- **Eventos ao vivo:** novos eventos a partir de hoje às 00:00, que continuam chegando enquanto a API estiver no ar.

O histórico é sempre o mesmo para a mesma data.

## Autenticação

Todos os endpoints de `/api/v1/`, exceto `/saude`, exigem este cabeçalho:

```
X-API-Key: epavi-teste-2026
```

## Limites e estabilidade

- No máximo **5 requisições por segundo**. Acima disso a API responde `429` com o cabeçalho `Retry-After`.
- Assim como uma API de produção, ela **pode ficar instável**: às vezes responde erro `5xx` ou demora alguns segundos para responder.

## Endpoints

### `GET /api/v1/saude`

Mostra o status da API e o período disponível. Não precisa de autenticação.

### `GET /api/v1/clientes`

Lista os clientes monitorados.

| Campo | Descrição |
|---|---|
| `id` | Identificador do cliente (`CLI-0001`) |
| `nome` | Nome do cliente |
| `tipo` | `residencial`, `comercial`, `agencia_bancaria` ou `industrial` |
| `cidade` | Cidade |
| `plano` | `Basico`, `Plus` ou `Premium` |
| `inicio_contrato` | Data de início do contrato |
| `ativo` / `data_cancelamento` | Situação do contrato |

### `GET /api/v1/tipos-evento`

Catálogo dos códigos de evento, com descrição, categoria e prioridade (`critica`, `alta`, `media`, `baixa` ou `informativa`).

### `GET /api/v1/eventos`

Eventos recebidos pela central, ordenados por `atualizado_em` (crescente) e depois por `id`.

| Parâmetro | Padrão | Descrição |
|---|---|---|
| `pagina` | 1 | Página (começa em 1) |
| `por_pagina` | 50 | Itens por página (máximo 200) |
| `atualizado_desde` | — | Opcional. Data ISO 8601 (ex.: `2026-10-01T00:00:00Z`). Retorna só os eventos com `atualizado_em` **maior ou igual** a esse valor |

Formato da resposta:

```json
{
  "pagina": 1, "por_pagina": 50, "total_registros": 10926, "total_paginas": 219,
  "dados": [
    {
      "id": 104925,
      "cliente_id": "CLI-0021",
      "codigo_evento": "E130",
      "zona": 3,
      "data_hora": "2026-08-25T03:21:32-03:00",
      "status": "encerrado",
      "operador": "Rafael Prado",
      "tempo_atendimento_seg": 212,
      "resultado": "falso_alarme",
      "observacao": null,
      "atualizado_em": "2026-08-25T06:25:40Z"
    }
  ]
}
```

| Campo | Descrição |
|---|---|
| `id` | Identificador único do evento |
| `cliente_id` | Cliente que gerou o evento |
| `codigo_evento` | Código do evento (veja `/tipos-evento`) |
| `zona` | Zona/sensor que disparou, quando houver |
| `data_hora` | Quando o evento aconteceu (horário de Brasília) |
| `status` | `aberto` → `em_atendimento` → `encerrado`. Eventos informativos ficam como `registrado` |
| `operador` | Operador da central que atendeu |
| `tempo_atendimento_seg` | Duração do atendimento, do início até o encerramento, em segundos |
| `resultado` | Desfecho do atendimento (ex.: `falso_alarme`, `viatura_enviada`) |
| `observacao` | Texto livre do operador |
| `atualizado_em` | Última alteração do registro (UTC) |

> **Atenção:** um evento pode mudar depois de capturado. Ele chega como `aberto` e depois passa para `em_atendimento` e `encerrado`. Quando isso acontece, o `atualizado_em` muda.

> **Atenção 2:** os dados vêm de uma integração real, e dados reais raramente chegam perfeitos. Confira o que você recebe antes de confiar nos números.
