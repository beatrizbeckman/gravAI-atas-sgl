# Experimentos de geração de atas

Compara modelos de LLM gerando atas a partir das mesmas transcrições, com o
mesmo prompt e o mesmo template, registrando tudo o que entra e sai.

## Rodar

```
uv run python experiments/run_experiments.py
uv run python experiments/run_experiments.py --models groq:openai/gpt-oss-20b groq:openai/gpt-oss-120b
uv run python experiments/run_experiments.py --transcripts datasets/reunioes/ES2004a/transcricao.json
uv run python experiments/run_experiments.py --extra '{"reasoning_effort": "low"}'
```

Padrão: as cinco reuniões do AMI em `datasets/reunioes/`, contra `groq:openai/gpt-oss-20b`, `groq:qwen/qwen3.8-27b` e
`groq:openai/gpt-oss-120b`. Um modelo é `<provedor>:<id>`; os provedores e a
variável do `.env` com a chave estão em `PROVIDERS` no script (`groq`, `openrouter`,
`deepinfra`, `openai`). O resultado vai para `results/<provedor do primeiro modelo>/<data_hora>/`
(fora do git; `git add -f` para guardar uma rodada). Rodadas feitas até agora:

| Pasta | Provedor | Modelos | Estado |
|---|---|---|---|
| `results/groq/2026-10-06_bateria_12k` | Groq gratuito | gpt-oss-20b, qwen3.8-27b (120b pendente) | 6 de 10 pares ok, 4 derrubados por limite |
| `results/openrouter/2026-10-07_bateria_12k` | OpenRouter gratuito | lfm-2.5-2.6b, nemotron-3-nano-30b, gemma-4-26b | 7 de 15 ok; gemma saturado, nemotron travou em 3 |
| `results/groq/_descartadas/` | Groq | smokes e a rodada com partes de 24 mil | só histórico |

## Comparativo entre provedores e modelos (rodadas de 06 e 07/10/2026)

Mesmas cinco reuniões, mesmo template (`dell`), partes de 12 mil caracteres, temperatura 0.
"Seções" é quantas das 10 seções do template vieram com conteúdo. "Tempo" é tempo de parede da
reunião inteira, incluindo as esperas por limite do provedor. "Nota" é de 0 a 5 contra o
`gabarito.md` (0 = não gerou ata), provisória até a avaliação manual na coluna `nota` do `resumo.csv`.

### Por reunião

| Provedor | Modelo | Reunião (falas) | Gerou? | Seções | Tempo | Nota |
|---|---|---|---|---|---|---|
| Groq | gpt-oss-20b | ES2004a (298) | sim | 5/10 | 2,5 min | 2 |
| Groq | gpt-oss-20b | ES2004b (509) | sim | 6/10 | 2h43 (quase tudo espera) | 3 |
| Groq | gpt-oss-20b | ES2004c (582) | não, limite após 2 chamadas | — | 8,8 min | 0 |
| Groq | gpt-oss-20b | ES2004d (705) | sim | 7/10 | 7 min | 2 |
| Groq | gpt-oss-20b | TS3003d (654) | não, limite antes da 1ª chamada | — | 5,5 min | 0 |
| Groq | qwen3.8-27b | ES2004a (298) | sim | 8/10 | 5 min | 3 |
| Groq | qwen3.8-27b | ES2004b (509) | não, limite após 2 chamadas | — | 7 min | 0 |
| Groq | qwen3.8-27b | ES2004c (582) | sim | 9/10 | 5,3 min | 4 |
| Groq | qwen3.8-27b | ES2004d (705) | sim | 9/10 | 10 min | 4 |
| Groq | qwen3.8-27b | TS3003d (654) | não, limite antes da 1ª chamada | — | 5,5 min | 0 |
| Groq | gpt-oss-120b | todas | não rodado (orçamento diário gasto na tradução) | — | — | — |
| OpenRouter | lfm-2.5-2.6b | ES2004a (298) | sim | 9/10 | 1 min | 2 |
| OpenRouter | lfm-2.5-2.6b | ES2004b (509) | sim | 9/10 | 1,5 min | 3 |
| OpenRouter | lfm-2.5-2.6b | ES2004c (582) | sim | 9/10 | 1,1 min | 1 |
| OpenRouter | lfm-2.5-2.6b | ES2004d (705) | sim | 9/10 | 1,3 min | 2 |
| OpenRouter | lfm-2.5-2.6b | TS3003d (654) | sim | 9/10 | 1,7 min | 2 |
| OpenRouter | nemotron-3-nano-30b | ES2004a (298) | sim | 8/10 | 19 min | 3 |
| OpenRouter | nemotron-3-nano-30b | ES2004b (509) | sim (resumo em inglês) | 8/10 | 35 min | 3 |
| OpenRouter | nemotron-3-nano-30b | ES2004c (582) | não, 4 respostas truncadas e conexão caiu | — | 5h18 | 0 |
| OpenRouter | nemotron-3-nano-30b | ES2004d (705) | não, conexão caiu antes da 1ª resposta | — | 2h28 | 0 |
| OpenRouter | nemotron-3-nano-30b | TS3003d (654) | não, erro de conexão | — | 1 s | 0 |
| OpenRouter | gemma-4-26b | todas | não, 429 do upstream em todas as tentativas | — | 5,6 min cada | 0 |

### Por modelo

| Provedor | Modelo | Atas geradas | Seções (média das geradas) | Tempo por reunião (geradas) | Nota média (geradas) | Nota média (0 nas falhas) | Custo |
|---|---|---|---|---|---|---|---|
| Groq | qwen3.8-27b | 3/5 | 8,7/10 | 5 a 10 min | **3,7** | 2,2 | sem preço na tabela |
| Groq | gpt-oss-20b | 3/5 | 6,0/10 | 2,5 min a 2h43 | 2,3 | 1,4 | US$ 0,016 na rodada |
| OpenRouter | nemotron-3-nano-30b | 2/5 | 8,0/10 | 19 a 35 min | 3,0 | 1,2 | 0 |
| OpenRouter | lfm-2.5-2.6b | **5/5** | 9,0/10 | **1 a 2 min** | 2,0 | 2,0 | 0 |
| OpenRouter | gemma-4-26b | 0/5 | — | — | — | 0 | 0 |

Leitura: "seções preenchidas" não mede qualidade. O LFM 2.6B preenche 9 de 10 sempre, e é o
pior em conteúdo, porque inventa prazos, status, responsáveis e horário da próxima reunião. O
qwen3.8-27b preenche menos e acerta mais. As falhas do Groq são de limite do plano gratuito e
somem com crédito pago ou rerodando em outro horário; as do Nemotron e do Gemma são do próprio
provedor gratuito (saturação) e não dependem de nós.

## O que fica registrado

Por par (transcrição, modelo), uma pasta com:

- `prompts/NN_system.txt`, `NN_user.txt`, `NN_raw.txt`: cada chamada ao LLM, exatamente
  como foi enviada e como voltou. Uma transcrição longa gera várias (partes + consolidação).
- `minutes.json`: a ata depois do parser, o que `GET /minutes/jobs/{id}/result` devolveria.
- `ata.docx`: o Word renderizado.
- `meta.json`: modelo, status, código de erro, partes, chamadas, repetições, segundos,
  tokens de entrada/saída/raciocínio, custo estimado, `finish_reason` de cada chamada,
  quantas vezes o modo JSON falhou e caiu para texto livre, quantas respostas foram cortadas.

E, na raiz da rodada, `resumo.csv` e `resumo.md` com uma linha por par, reescritos
depois de cada execução. A coluna `nota` fica vazia para ser preenchida à mão.

## Como avaliar

Para cada ata, abrir `minutes.json` ao lado do `gabarito.md` da transcrição e dar
nota de 1 a 5 considerando:

1. As decisões do gabarito aparecem em "decisões" ou no resumo?
2. Pendências e plano de ação têm responsável coerente com quem falou?
3. Nada foi inventado (datas, números, nomes fora da lista)?
4. JSON válido de primeira (`retries` = 0 e `json_mode_fallbacks` = 0)?
5. Texto de ata, não cópia da fala.

Anotar padrões em `observacoes` (ex.: "deixou decisões vazio apesar de três acordos
no gabarito"). A tabela final do artigo sai de `resumo.csv` mais essas notas.

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

