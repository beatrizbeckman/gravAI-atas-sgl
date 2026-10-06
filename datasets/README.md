# Dataset de transcrições de reunião

Conjunto de transcrições usado para avaliar a geração de atas (Parte 1 do TCC).
Cada reunião está em `reunioes/<id>/` no formato que o pipeline consome, mais um
gabarito escrito por humanos dizendo o que a ata precisa conter.

## Origem

| Fonte | O que fornece | Licença |
|---|---|---|
| [AMI Meeting Corpus](https://groups.inf.ed.ac.uk/ami/corpus/) | reuniões reais gravadas em Edimburgo, Idiap e TNO (2004–2006) | CC BY 4.0 |
| [QMSum](https://github.com/Yale-LILY/QMSum) (Zhong et al., 2021) | transcrição do AMI com pontuação, maiúsculas e papel do falante; resumo geral, lista de tópicos e perguntas/respostas escritos por anotadores humanos | MIT (anotações), AMI CC BY 4.0 (texto) |
| [edinburghcstr/ami](https://huggingface.co/datasets/edinburghcstr/ami) (Hugging Face) | tempos de início e fim de cada segmento, usados para a duração real da reunião | CC BY 4.0 |

As reuniões são o **cenário AMI**: uma equipe de quatro pessoas (gerente de projeto,
designer industrial, designer de interface e marketing) projeta um novo controle
remoto de TV ao longo de quatro reuniões: kickoff, projeto funcional, projeto
conceitual e projeto detalhado. São reuniões reais, com interrupções, hesitações e
assuntos que vão e voltam, mas com roteiro de projeto dado aos participantes.

## Reuniões incluídas

| Pasta | Fase | Equipe | Falas | Observação |
|---|---|---|---|---|
| `ES2004a` | Kickoff | ES2004 | ~300 | curta (~19 min); cabe em uma chamada ao LLM |
| `ES2004b` | Projeto funcional | ES2004 | ~500 | longa; força divisão em partes e consolidação |
| `ES2004c` | Projeto conceitual | ES2004 | ~600 | longa |
| `ES2004d` | Projeto detalhado | ES2004 | ~750 | longa, muitas falas curtas |
| `TS3003d` | Projeto detalhado | TS3003 | ~700 | outra equipe, outra dinâmica |

Os testes automatizados usam a reunião ES2004a (a mais curta) como dado de entrada;
não existem mais transcrições inventadas no repositório.

## Formato de cada pasta

- `transcricao.json`: `{template, header, utterances, meta}`. É exatamente o que
  `python -m gravai.minutes.generate` e `POST /minutes/from-transcript` recebem. Template
  `dell` (reunião de projeto), cabeçalho fictício (projeto "Controle Remoto
  Universal", nº, data e horário coerentes com a duração).
- `original.json`: as mesmas falas em inglês, depois da limpeza.
- `gabarito.md`: resumo humano, tópicos e perguntas/respostas traduzidos, mais a
  tabela que liga o nome fictício ao papel do AMI, e o original em inglês.
- `traducao_cache.json`: blocos já traduzidos (fora do git); permite retomar.

## Como foi construído

`build_ami_dataset.py` faz tudo e é reexecutável:

1. Baixa o JSON do QMSum da reunião (cache em `raw/qmsum/`).
2. Limpa marcadores `{vocalsound}`, `{disfmarker}`, `{gap}`, espaços antes de
   pontuação e contrações; descarta falas que eram só som vocal.
3. Troca os papéis por nomes fictícios em português (uma tabela por equipe, para
   os nomes ficarem estáveis dentro da série).
4. Gera `start`/`end`: a duração real da reunião vem do edinburghcstr/ami e é
   distribuída entre as falas proporcionalmente ao número de palavras, com uma
   pausa curta entre falas. Quando a API não responde, usa 2,6 palavras/s.
5. Traduz as falas em blocos de 30 com um modelo grande via API online, com a
   instrução de **manter o registro oral** (hesitações, frases incompletas), e
   traduz o gabarito em registro formal. Reexecutar reaproveita o cache; o
   modelo que traduziu cada bloco fica registrado no cache e o conjunto deles
   em `meta.translation_model` da transcrição.

Em 06/10/2026: ES2004a–d e as falas 0–269 de TS3003d foram traduzidas com
`openai/gpt-oss-120b`; o orçamento diário gratuito do Groq (200 mil tokens) acabou e o
restante de TS3003d foi traduzido com `openai/gpt-oss-20b`, com `reasoning_effort: low`
e `max_tokens: 8000` (sem o teto, o raciocínio do modelo consumia a resposta e a
tradução vinha cortada). Falas que a primeira versão do script deixou em inglês
(quando o modelo omitia ids) foram retraduzidas pelo passo de reparo, com o 20b. O
cache de cada reunião registra o modelo por bloco em `_models`.

```
uv run python datasets/build_ami_dataset.py                  # as cinco
uv run python datasets/build_ami_dataset.py ES2004a          # uma
uv run python datasets/build_ami_dataset.py --no-translate   # só converter
uv run python datasets/build_ami_dataset.py --model openai/gpt-oss-120b
```

## Limitações, a declarar no artigo

- A tradução remove os erros típicos de reconhecimento de fala em português e a
  fala sobreposta duplicada que o GravAI produz. Pelo menos uma reunião real
  gravada pelo bot entra como validação antes do fim da Parte 1.
- Os tempos são aproximados por fala; só a duração total é real.
- Todas as reuniões são do mesmo domínio (projeto de produto) e usam o template
  `dell`. Os templates `professores` e `daily` só são exercitados pelos testes
  unitários, com a mesma transcrição.
- O gabarito do QMSum é um resumo, não uma ata: ele diz o que foi discutido e
  decidido, mas não traz "plano de ação com responsável e prazo" no formato da
  tabela. A nota manual compara conteúdo, não forma.
