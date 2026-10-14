# Relatório · Central de Monitoramento

## 1. Para a gestão: o que o painel mostra e o que os dados dizem

O painel mostra, para qualquer período, cidade ou tipo de cliente: quantos eventos chegaram à
central por dia e de que tipo; quais estão abertos ou em atendimento neste momento; quanto
tempo a equipe leva para encerrar um evento, por prioridade e por operador; quais clientes mais
disparam o alarme e quantos desses disparos foram falsos; e quais clientes têm problemas
técnicos repetidos (comunicação, energia, bateria). Uma última seção mostra o que a integração
precisou corrigir nos dados antes de gravar.

Nos 90 dias analisados, três conclusões:

**1. 83% dos alarmes são falsos.**
Dos 268 disparos de intrusão, 223 (83%) terminaram como falso alarme. Só duas instalações,
Textil Central Ltda e Residência Martins – Ap 302, respondem por 81 disparos (30% do total),
com 96% e 91% de falso alarme, disparando quase todo dia. Isso pode ocorrer por algum sensor com defeito ou algo nesse sentido, deve ser um ponto de atenção. Uma visita técnica nesses dois endereços tira da fila da central cerca de um disparo por dia e evita acionar viatura à toa.

**2. Três clientes estão com o equipamento falhando e podem estar desprotegidos sem saber.**
Loja Aurora, Usinagem Nova Era Ltda e Farmácia Sol Nascente somam 143 falhas de comunicação e
passaram entre 27% e 36% dos dias sem enviar o teste periódico que o painel de alarme deveria
mandar todo dia. Se fica um dia sem teste, é um dia que o imóvel pode estar desprotegido. Os
outros 42 clientes ficaram no máximo 5 dias sem teste no mesmo período.

**3. A carga pesada da central é à noite, e um quarto do tempo de atendimento vai para
alarme falso.** O turno da noite (19h às 7h) recebe 60% dos atendimentos e 71% dos disparos de
intrusão, com o mesmo número de operadores do dia. Mesmo assim a prioridade é respeitada:
eventos críticos são encerrados em 1 min 36 s em média, alta prioridade em 5 min, média em 12
min e baixa em 33 min. O que pesa é o que não deveria estar na fila: os falsos alarmes consomem
20 das 85 horas de atendimento do período, quase um quarto do tempo da equipe. E os 80 casos
encerrados como "sem contato" (ninguém atendeu nos telefones cadastrados) são os mais demorados,
quase 13 minutos cada. Dois ajustes baratos: reforçar a escala da noite nos horários de pico de
disparo e revisar os telefones de contato dos clientes que mais caem em "sem contato".

## 2. Se a captura rodar duas vezes seguidas, o que acontece no banco?

Nada muda. A segunda rodada lê a **marca d'água** (o maior `atualizado_em` já gravado) e pede à
API só o que tem `atualizado_em` maior ou igual a ela. Volta um registro, o da própria
fronteira, porque o filtro é "maior ou igual". A gravação compara o `atualizado_em` recebido com
o gravado: é igual, então não faz nada. A rodada fica registrada em `execucoes` com
`1 lido, 0 novos, 0 atualizados, 1 inalterado`. Foi exatamente isso que aconteceu na execução 2.

Isso vale também para a primeira rodada, que recebe 166 linhas duplicadas da própria API: o
`id` é chave primária, então a segunda cópia é reconhecida e contada como "inalterado", nunca
inserida. E se um evento tiver evoluído (de `aberto` para `encerrado`), a nova versão tem
`atualizado_em` maior e **substitui** a antiga; uma versão mais antiga que chegasse atrasada
seria descartada.

## 3. Se a API ficar fora do ar por 2 horas, o que acontece quando ela voltar?

Durante a queda, cada rodada agendada tenta 8 vezes com espera crescente (0,5 s até 30 s),
registra `API indisponível` no log, sai com código 1 e não toca no banco. Se a queda pegar uma
rodada no meio, as páginas já confirmadas ficam gravadas, porque cada página é confirmada junto
com a marca d'água antes de pedir a próxima.

Quando a API volta, a primeira rodada pede `atualizado_desde = marca d'água`, que ainda aponta
para o último registro lido antes da queda. A API devolve tudo o que mudou nas 2 horas: eventos
novos e eventos que mudaram de status. Como a ordenação é por `atualizado_em` e a leitura é por
cursor, nada é pulado, mesmo que a lista mude enquanto estou lendo. O único efeito visível é que
o painel fica 2 horas sem atualização, e o ponto ao lado de "Dados da captura" fica amarelo
depois de 15 minutos sem rodada.

## 4. O total de eventos no banco é igual ao `total_registros` da API?

Não. No momento da primeira captura a API informava `total_registros = 11.139` e o banco ficou
com **10.975 eventos**. A diferença são **164 linhas** e tem duas causas:

- **166 linhas duplicadas** que a API entrega com o mesmo `id` e o mesmo conteúdo (1,5% do
  histórico). O `total_registros` conta essas repetições; o banco, não.
- Eventos ao vivo que chegaram entre a consulta do total e a captura (a API gera eventos novos
  enquanto está no ar), que explicam os 2 registros de diferença no sentido contrário.

O banco é que está certo: `COUNT(*) = COUNT(DISTINCT id) = 10.975`.

## 5. Um trecho de código, com as minhas palavras

Escolhi a função que limpa o tempo de atendimento, em `central/normalizacao.py` (versão resumida; a original também recusa um texto que não seja número):

```python
def _parse_tempo(valor, status, problemas):
    if valor is None:
        if status == "encerrado":
            problemas.append(Problema("tempo_atendimento_seg", "tempo_ausente", None))
        return None
    if isinstance(valor, str):
        problemas.append(Problema("tempo_atendimento_seg", "tempo_texto", valor))
        valor = int(valor.strip())
    if valor < 0:
        problemas.append(Problema("tempo_atendimento_seg", "tempo_negativo", str(valor)))
        return None
    return int(valor)
```

O tempo de atendimento é a base de um dos indicadores que a gestão pediu (tempo médio por
prioridade e por operador), e ele chegava da API de três jeitos errados. Na captura de 13/10, 7
eventos encerrados vieram sem tempo, 10 vieram com o número escrito como texto (`"226"` em vez de
`226`) e 3 vieram negativos.

A função trata cada caso de um jeito. Se veio vazio, fica vazio: não invento um tempo, e o evento
só fica de fora da média. Se veio como texto, converto para número, porque ali o valor está certo,
só no formato errado. Se veio negativo, eu descarto o valor. Pensei em só inverter o sinal, mas
não tenho como saber se o erro foi só o sinal ou outro qualquer, e um número errado puxaria a
média para o lado errado. Com 3 casos em mais de 600 atendimentos, perder esses valores não muda
o resultado, e colocar um valor errado poderia mudar.

Em todos os casos a função anota o que encontrou, com o valor original, em vez de corrigir em
silêncio. Essas anotações vão para a tabela `problemas_dados` e aparecem na seção "Qualidade dos
dados" do painel. Assim qualquer pessoa consegue ver o que foi mexido e conferir o dado que
chegou da central.
