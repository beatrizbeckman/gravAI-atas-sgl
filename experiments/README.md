# Experimentos de geração de atas

Comparação de modelos de LLM, tendo como base as mesmas reuniões

## Rodar as reunioes nas llm

```
uv run python experiments/run_experiments.py # as 5 reuniões nos 3 modelos do Groq 
uv run python experiments/run_experiments.py --models groq:openai/gpt-oss-20b groq:openai/gpt-oss-120b # Escolhe os modelos (no exemplo, só 2)
uv run python experiments/run_experiments.py --transcripts datasets/reunioes/ES2004a/transcricao.json # Escolhe as reuniões (no exemplo, só a ES2004a)
```

- Nome do modelo: é sempre `provedor:id`. O provedor é a empresa que hospeda o modelo. Em `groq:openai/gpt-oss-20b`, o provedor é o Groq e o modelo é `openai/gpt-oss-20b`.
- Chaves de acesso: cada provedor tem sua chave no `.env`. O dicionário PROVIDERS, no script, indica qual variável corresponde a cada um.
- Os resultados: em `results/<provedor do primeiro modelo>/<data_hora>/`.
- Para guardar uma rodada, use `git add -f`.Rodadas feitas até agora:

## Comparativo entre provedores e modelos

Mesmas cinco reuniões, template `dell`."Seções" é quantas das 10 vieram com conteúdo; tempo de parede, com as esperas por limite do provedor.

| Provedor | Modelo | Atas geradas | Seções | Tempo por ata | Custo por ata |
|---|---|---|---|---|---|
| Groq | qwen3.8-27b | 4/5 | 8,5/10 | 4,5 a 10 min | sem preço na tabela |
| Groq | gpt-oss-120b | 5/5 | 6,8/10 | 1,7 a 11 min | US$ 0,010 |
| Groq | gpt-oss-20b | 5/5 | 6,4/10 | 2,5 a 10 min | US$ 0,006 |
| OpenRouter | nemotron-3-nano-30b | 4/5 | 8,2/10 | 13 a 35 min | 0 |
| OpenRouter | lfm-2.5-2.6b | 5/5 | 9,0/10 | 1 a 2 min | 0 |
| OpenRouter | gemma-4-26b | 0/5 | — | — | 0 |
| Google | gemini-3-flash-preview | 4/5 | 8,0/10 | 0,7 a 1,6 min | sem preço na tabela |

"seções preenchidas" não mede qualidade;
O *LFM 2.6B* preenche 9 de 10 sempre e é o
pior em conteúdo, porque inventa prazos, status, responsáveis e próxima reunião.
O *qwen3.8-27b* acerta mais, mas o plano gratuito do Groq o limita a 1 000 tokens de saída por minuto e a reunião ES2004b não passou em 4 tentativas.
O *gpt-oss-120b* é fiel e não inventa, mas deixa "decisões" vazio ou contraditório.
O *gemini-3-flash-preview* registra mais decisões e foi o mais rápido junto com o LFM, mas a cota acabou na TS3003d e ele copiou para a Paula, na ES2004c, o sobrenome do exemplo do prompt. A comparação com o gpt-oss-120b está no [fim deste arquivo](#gemini-3-flash-preview-x-gpt-oss-120b).

| Faixa | Modelos | Bilhões de parâmetros |
|---|---|---|
| Pequeno | lfm-2.5-2.6b | 2,6 |
| Médio | gpt-oss-20b | 20 |
| Médio | gemma-4-26b | 26 |
| Médio | qwen3.8-27b | 27 |
| Médio | nemotron-3-nano-30b | 30 |
| Grande | gpt-oss-120b | 120 |
| Sem faixa | gemini-3-flash-preview | Não divulgado pelo Google |

## O que fica registrado quando rodo os experimentos

(transcrição, modelo), cada pasta com:

- `prompts/`: tudo o que foi enviado ao modelo e o que ele respondeu, sem nenhuma alteração. Uma reunião longa é cortada em partes, e cada parte vira uma chamada ao modelo. No fim, mais uma chamada junta tudo em uma única ata (a consolidação). Cada chamada tem um número (`NN`: 01, 02...) e gera três arquivos:
  - `NN_system.txt`: as instruções fixas enviadas ao modelo, como o formato da ata.
  - `NN_user.txt`: o conteúdo daquela chamada, como um trecho da transcrição.
  - `NN_raw.txt`: a resposta do modelo, do jeito que veio.
- `minutes.json`: a ata organizada em campos, depois de o sistema ler a resposta do modelo. É o mesmo conteúdo que a API do GravAI devolveria para essa reunião.
- `ata.docx`: a ata final em Word.
- `meta.json`: os dados técnicos do teste:
  - **Identificação e resultado:** qual modelo foi usado, se o teste deu certo e, se falhou, o código do erro.
  - **Volume de trabalho:** em quantas partes a reunião foi cortada, quantas chamadas foram feitas e quantas tiveram que ser repetidas.
  - **Tempo e custo:** duração em segundos, tokens gastos (o volume de texto processado) na entrada, na saída e no raciocínio do modelo, e o custo estimado.
  - **Problemas nas respostas:** por que cada resposta terminou (`finish_reason`; por exemplo, se chegou ao fim ou atingiu o limite de tamanho), quantas vieram cortadas e quantas vezes o modelo não conseguiu responder no formato JSON e o sistema precisou pedir em texto livre.


E, na raiz da rodada, `resumo.csv` e `resumo.md` com uma linha por par, reescritos
depois de cada execução.

## Como avaliar

A qualidade das atas será por pessoas em um formulário, comparando trechos da reunião
com as atas de cada modelo. A reunião, os trechos, as perguntas e a análise estão em
[`avaliacao_forms/README.md`](avaliacao_forms/README.md).

## Custos

`precos.json` tem US$ por milhão de tokens por modelo. Modelo ausente sai como `n/d`.
Atualizar ao incluir modelo novo; os valores são os da página de preços do provedor
na data indicada no arquivo.

## Limites da conta gratuita do Groq (medidos em 06/10/2026)

| Modelo | Por requisição | Por minuto | Por dia |
|---|---|---|---|
| `openai/gpt-oss-20b` | 8 000 tokens (entrada + saída esperada), senão HTTP 413 | 8 000 TPM | — |
| `qwen/qwen3.8-27b` | 7 000 tokens de entrada (413) | **1 000 tokens de saída** (429), o que mal cabe uma ata | — |
| `openai/gpt-oss-120b` | — | 8 000 TPM | **200 000 tokens**; a tradução do dataset consumiu o dia 06/10 |

Consequências práticas:

- Rodar sempre com `--max-chars 12000`: cada parte da transcrição fica em ~4 mil
  tokens e o prompt de sistema em ~1,5 mil, abaixo do teto por requisição. O padrão
  do pipeline (24 000) foi pensado para Ollama e dá 413 no Groq gratuito.
- Com 12 000 a reunião ES2004a (13 mil caracteres) já vira 2 partes + consolidação,
  e as longas viram 3 partes + consolidação. Isso faz parte da condição experimental
  e deve ser dito na tabela.
- O runner espera e repete em 429 (20, 40, 60, 90, 120 s). Uma rodada completa leva
  bem mais tempo pelas pausas do que pelas chamadas em si.
- O `gpt-oss-120b` precisa ser rodado em outro dia ou com crédito pago. Comando para
  completar a mesma rodada (os pares já prontos são pulados):

```
uv run python experiments/run_experiments.py --max-chars 12000 --models groq:openai/gpt-oss-120b --out experiments/results/groq/2026-10-06_bateria_12k
```

## Modelos gratuitos do OpenRouter (medidos em 07/10/2026)

Chave sem cartão em openrouter.ai; modelos com sufixo `:free`; variável `OPEN_ROUTER` no `.env`.
Os erros do upstream vêm dentro de uma resposta HTTP 200 (`{"error": {"code": 502, ...}}`);
`openai_chat` lê esse campo e `openai_chat_retrying` repete quando o código é 429 ou 5xx.

| Modelo | O que aconteceu |
|---|---|
| `google/gemma-4-26b-a4b-it:free`, `google/gemma-4-31b-it:free` | 429 "temporarily rate-limited upstream" em todas as tentativas, inclusive após 5 esperas (5,5 min por par). Zero atas. |
| `liquid/lfm-2.5-2.6b:free` | 5/5 atas, 60 a 104 s cada, JSON válido de primeira. Qualidade fraca (ver `resumo.md`). |
| `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` | 2/5 atas. O raciocínio ignora `max_tokens` e chega a 32 768 tokens por chamada (10 a 13 min); 4 respostas truncadas, depois "Response ended prematurely" e 502 "Worker local total request limit reached". ES2004c levou 5h18 para falhar. |

Consequências práticas:

- Modelo gratuito saturado não é erro do nosso lado: o runner marca `llm_unreachable` e segue.
  Repetir em outro horário com o mesmo `--out` completa a rodada.
- Modelos de raciocínio precisam de teto de raciocínio, não só de `max_tokens`. No OpenRouter
  isso vai em `--extra '{"reasoning": {"effort": "low"}}'`; sem isso o tempo e os tokens explodem.
- O LFM 2.6B mostra o limite inferior de tamanho: preenche todas as seções, mas inventa prazos,
  status e próxima reunião. Serve como baseline negativo na tabela do artigo.

## Gemini 3 Flash Preview x gpt-oss-120b

Rodada em `results/gemini/` (02/11/2026), com partes de 12 mil caracteres e template `dell`. O Gemini também entra no [formulário de avaliação](avaliacao_forms/README.md), com uma ata nova da ES2004a.

O `gpt-oss-120b` é o modelo padrão do serviço. A comparação usa as duas reuniões em que ele rodou com quase o mesmo prompt do Gemini (`results/groq/2026-10-29_prompt_novo/`): a única diferença é o horário opcional no prazo. A qualidade vem de uma leitura contra o gabarito e a transcrição, não do formulário.

| Critério | gpt-oss-120b (padrão) | gemini-3-flash-preview |
|---|---|---|
| **Atas geradas nesta comparação** | 2/2 | 2/2 |
| **Atas geradas nas 5 reuniões** | 5/5 (prompt anterior) | 4/5 (TS3003d: cota esgotada) |
| **Seções preenchidas: ES2004a / ES2004d** | 4/10 / 8/10 | 7/10 / 9/10 |
| **Decisões registradas: ES2004a / ES2004d** | 0 / 5 | 5 / 8 |
| **Tempo total: ES2004a / ES2004d** | 134 s / 606 s | 42 s / 98 s |
| **Tempo só nas chamadas: ES2004a / ES2004d** | 13 s / 31 s | 42 s / 98 s |
| **Tokens: ES2004a / ES2004d** | 18 233 / 39 293 | 18 474 / 41 522 |
| **Custo estimado: ES2004a / ES2004d** | US$ 0,005 / US$ 0,012 | Sem preço na tabela |
| **Próxima reunião na ES2004a ("em meia hora")** | Vazia | 02/03 às 14:49 (correta) |
| **Reconhecimento de voz na ES2004d** | Aprovado como decisão, embora tenha saído do projeto | Removido do padrão, custo de 12,35 euros |
| **Principais erros** | Decisões vazias na ES2004a; 23 tópicos fragmentados na ES2004d | Preço e menu fora das decisões na ES2004a; "foco inicial" em Austrália e EUA, que não foi dito |

**Conclusão.** Nessas duas reuniões, o Gemini fez atas mais completas e acertou decisões que o `gpt-oss-120b` deixou vazias ou contradisse. O tempo total menor vem de não ter esperado por limite nessas reuniões; em cada chamada, o Groq foi cerca de três vezes mais rápido. Isso não muda o modelo padrão: a cota do Gemini acabou antes da quinta ata, o custo não foi levantado e são só duas reuniões, avaliadas sem o formulário.

Nas outras reuniões do Gemini (ES2004b e ES2004c), a leitura contra o gabarito também encontrou decisões coerentes, mas a ES2004b não registra a tampa flip como decisão. O `gpt-oss-120b` não rodou nessas duas com o mesmo prompt, então elas ficam fora da tabela.

**Nome vindo do prompt.** Na ES2004c, o Gemini deu à Paula um sobrenome que não existe na transcrição: copiou o exemplo da regra de nomes do prompt de sistema. Em 02/11/2026 o exemplo passou a usar um nome fictício ("Ana Clara Lima"); as rodadas anteriores guardam o prompt antigo em `prompts/`.

