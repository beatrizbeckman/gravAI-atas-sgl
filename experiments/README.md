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
variável do `.env` com a chave estão em `PROVIDERS` no script. O resultado vai
para `results/<data_hora>/` (fora do git; `git add -f` para guardar uma rodada).

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
uv run python experiments/run_experiments.py --max-chars 12000 --models groq:openai/gpt-oss-120b --out experiments/results/2026-10-06_bateria_12k
```
