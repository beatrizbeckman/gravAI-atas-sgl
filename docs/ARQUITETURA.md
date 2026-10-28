# GravAI · Geração de atas — como o sistema funciona por dentro

Documento de apoio para a orientação do TCC. A ideia aqui é explicar, de forma prática, o que cada parte do código faz, como as partes se conectam e o que acontece de verdade quando alguém pede uma ata. Está escrito para quem conhece o problema, mas não leu o código.

Estado do repositório em 01/10/2026, branch `feat/minutes-part1`. Tudo o que está descrito aqui existe e roda. A seção 13 diz o que ainda falta.

---

## 1. A ideia em uma frase

O GravAI entra numa reunião do Teams como se fosse um participante, grava o áudio, descobre quem falou quando, transcreve cada pessoa com Whisper, junta tudo numa transcrição única e manda para um LLM preencher um modelo de ata. O resultado é um `.docx` pronto para revisar.

Em forma de desenho, do áudio até o documento:

```
 link do Teams
      │
      ▼
 ┌──────────────┐   áudio da reunião + "quem está falando"    ┌──────────────┐
 │  gravai/recording/  │ ───────────────────────────────────────────► │   gravai/slicing/   │
 │  bot entra e │   track_mainAudio.wav + vad_timeline.json    │  recorta um  │
 │  grava       │                                              │  wav por     │
 └──────────────┘                                              │  pessoa      │
                                                               └──────┬───────┘
                                                                      │ track_<pessoa>.wav
                                                                      ▼
 ┌──────────────┐   um JSON de segmentos por pessoa             ┌──────────────┐
 │  gravai/minutes/    │ ◄──────────────────────────────────────────── │  gravai/transcription/ │
 │  transcript_ │   track_<pessoa>_transcription_segments.json  │  Whisper em  │
 │  normalizer  │                                               │  cada wav    │
 └──────┬───────┘                                               └──────────────┘
        │ lista única e cronológica de falas: quem, quando, o quê
        ▼
 ┌──────────────────────────────────────────────────────────────────────────┐
 │  gravai/minutes/  (geração da ata)                                              │
 │  templates ──► prompt_builder ──► llm ──► prompt_builder.parse ──► docx  │
 └──────────────────────────────────────────────────────────────────────────┘
        ▲                                                           │
        │ gravai/jobs/ roda isso em segundo plano, um por vez               ▼
 ┌──────────────┐                                              ata_dell_2026-10-01_projeto.docx
 │   gravai/api/       │  POST /minutes/...  → job_id → GET /jobs/{id} → download
 └──────────────┘
        ▲
        │ HTTP
   SGL ou página /demo
```

Duas coisas para guardar desse desenho:

- **Existem dois mundos.** O de cima (gravar, separar, transcrever) já existia no GravAI original. O de baixo (`gravai/minutes/`, `gravai/jobs/`, `/minutes/*`) é o que foi construído na Parte 1 do TCC. Eles se encontram num único ponto: a transcrição normalizada.
- **Dá para entrar em qualquer ponto.** Quem já tem a transcrição não precisa gravar nada. Quem já gravou não precisa gravar de novo. Isso vira três endpoints diferentes, explicados na seção 9.

---

## 2. Mapa das pastas

| Pasta / arquivo | Papel | Origem |
|---|---|---|
| `gravai/recording/` | Bot que entra no Teams e grava | GravAI original, ajustado |
| `gravai/slicing/` | Descobre quem falou quando e recorta o áudio por pessoa | GravAI original, ajustado |
| `gravai/transcription/` | Manda cada wav para o servidor Whisper | GravAI original |
| `gravai/models.py` | Classes de dados compartilhadas (sessão, trilha, fala) | GravAI original, com `Utterance` adicionada |
| `gravai/legacy/handle_data/` | Leitura dos JSONs de transcrição antigos | GravAI original, ainda usado como fallback |
| `gravai/legacy/llm_analyser/` | Análise de debate via Groq, código antigo | GravAI original, não faz parte da ata |
| `gravai/minutes/` | **Geração da ata**: templates, prompt, LLM, docx | TCC Parte 1 |
| `gravai/jobs/` | **Fila de trabalhos** em SQLite para rodar em segundo plano | TCC Parte 1 |
| `gravai/api/app.py` | Servidor FastAPI, endpoints antigos de gravação | GravAI original, ajustado |
| `gravai/api/minutes.py` | **Endpoints `/minutes/*`** | TCC Parte 1 |
| `gravai/api/demo.py` + `gravai/api/static/demo.html` | **Página de demonstração** que faz o papel do SGL | TCC Parte 1 |
| `gravai/config.py` | Leitura do `.env` | GravAI original, com variáveis novas |
| `docs/API_MINUTES.md` | Contrato HTTP da API de atas | TCC Parte 1 |
| `docker/Dockerfile`, `docker-compose*.yaml`, `Makefile` | Empacotamento e comandos | GravAI original, ajustado |
| `tmp/` | Gravações, docx gerados e o SQLite dos jobs. Não vai para o git | runtime |

Teste automatizado: 115 testes em `tests/` (`tests/minutes`, `tests/jobs`, `tests/api`, dados em `tests/conftest.py` vindos do dataset), todos passando sem precisar de LLM, Whisper ou Teams. Reorganização de 07/10/2026: todo o código ficou dentro do pacote `gravai/`, os testes em `tests/`, os arquivos Docker em `docker/`.

---

## 3. Módulo de gravação (`gravai/recording/`)

### O que ele resolve

O Teams não dá o áudio da reunião para ninguém. A saída do GravAI é entrar como um participante normal, dentro de um navegador controlado por código, e capturar o áudio que o próprio navegador recebe.

### Como funciona, passo a passo

1. **`gravai/recording/teams.py` abre um Chromium invisível** usando Playwright. Antes da página carregar, injeta dois scripts JavaScript na página do Teams.
2. **O primeiro script, `gravai/recording/common/rtc_intercept.js`, intercepta o WebRTC.** Ele troca a classe `RTCPeerConnection` do navegador por uma versão que avisa toda vez que chega uma trilha de áudio. Quando chega, ele liga essa trilha a um `AudioWorklet` (`audio_worklet_processor.js`), que entrega o áudio bruto em blocos de números float. Esses blocos são enviados por WebSocket para um servidor Python.
3. **O servidor Python, `gravai/recording/ws_audio_server.py`, grava o áudio em disco.** Roda como um processo separado, aberto quando a API sobe. Cada trilha vira um arquivo `track_<id>.wav` dentro de `tmp/<session_id>_tracks/`. Quando a trilha fecha, ele roda ffmpeg para corrigir o pitch, porque o áudio chega numa taxa que o navegador reporta errado, e escreve um arquivo `session_sidecar.json` com início e fim de cada trilha.
4. **O segundo script, `gravai/recording/teams/vad_observer.js`, observa quem está falando.** Isso é a parte mais criativa do GravAI. O Teams desenha um contorno animado no quadrado de quem está falando. Esse contorno é um `div` com `data-tid="voice-level-stream-outline"`, e o Teams adiciona classes CSS nele enquanto a pessoa fala. O script usa um `MutationObserver` para registrar toda mudança nessas classes, com o nome do participante e o timestamp. Em termos práticos: é um detector de atividade de voz feito a partir da interface, sem processar áudio.
5. **`teams.py` cuida da entrada na reunião.** Abre o link, clica em "continuar no navegador", fecha o diálogo de "continuar sem áudio ou vídeo", preenche o nome "GravAI Bot", clica em "Join now" e espera ser admitido da sala de espera. Tem tratamento para a tela de erro que o Teams mostra dentro do Docker e tira screenshots quando `RECORDING_DEBUG=true`.
6. **Durante a reunião**, a cada segundo ele esvazia a lista de eventos de voz da página e vigia três sinais de fim: "Did you leave by mistake?", "You've been removed" ou um botão "Rejoin". Tem também um teto de segurança, `MAX_RECORDING_SECONDS`, padrão duas horas.
7. **Ao terminar**, grava `vad_timeline.json` com todos os eventos e fecha o navegador. O servidor WebSocket fecha os wavs e escreve o sidecar.

### O que fica no disco ao final

```
tmp/<session_id>_tracks/
├── track_mainAudio-<id>.wav     áudio da reunião inteira, todo mundo misturado
├── session_sidecar.json         quando cada trilha começou e terminou
├── vad_timeline.json            eventos "fulano começou/parou de falar" com timestamp
└── after_join.png               screenshot logo após entrar (debug)
```

Ponto importante: **o Teams entrega uma única trilha de áudio com todos misturados**, chamada `mainAudio`. A separação por pessoa não vem do Teams. Ela é feita no próximo módulo, combinando esse áudio único com a linha do tempo de quem estava falando.

### Limitações conhecidas

- Uma reunião por vez. Existe uma trava, `RECORDING_LOCK` em `gravai/jobs/executors.py`, compartilhada entre os endpoints antigos e os jobs novos.
- Entrar na reunião leva de 40 segundos a dois minutos e meio dentro do Docker.
- Se duas pessoas falam ao mesmo tempo, as duas janelas de fala se sobrepõem e o áudio das duas aparece nas duas trilhas. Isso é tratado depois, na normalização, e é exatamente o motivo da Parte 2 do TCC.

---

## 4. Módulo de separação de falantes (`gravai/slicing/slice.py`)

### O que ele resolve

Transformar "um wav com todo mundo" mais "uma lista de quando cada pessoa falou" em "um wav por pessoa".

### Como funciona

1. **`_extract_session_dto`** espera o `session_sidecar.json` ficar completo, acha o `track_mainAudio*.wav` e carrega o `vad_timeline.json`. Tudo vira um `SessionDataDTO`, definido em `gravai/models.py`.
2. **`_process_participant_data`** agrupa os eventos por elemento da interface, ou seja, por participante.
3. **`_find_participant_tracks`** decide o que é "falando" e o que é "calado". A regra: para cada pessoa, o maior número de classes CSS visto no contorno significa falando, qualquer número menor significa calado. Cada troca de estado vira um evento START ou END com o tempo em segundos desde o início da gravação. Quem nunca mudou de estado nunca falou e é descartado.
4. **`create_session`** gera um wav por pessoa com ffmpeg. O truque é não cortar o áudio: ele pega o `mainAudio` inteiro e **zera o volume fora das janelas** em que a pessoa estava falando. Assim o wav de cada pessoa tem exatamente a mesma duração do áudio original e os tempos continuam alinhados entre todas as trilhas. Isso é o que permite, lá na frente, simplesmente ordenar as falas de todo mundo por tempo.
5. Devolve um `Session` com `tracks = {id_do_participante: {nome, caminho do wav}}`, que a API salva como `session_metadata.json`.

### Por que isso importa para a ata

Porque é daqui que sai o **nome** de quem falou. O nome vem do `data-tid` da interface do Teams, que é o nome de exibição do participante. Não há reconhecimento de voz nenhum na Parte 1. Se alguém entra como "Convidado", a ata vai dizer "Convidado".

---

## 5. Módulo de transcrição (`gravai/transcription/`)

### O que ele resolve

Transformar cada wav por pessoa em texto com tempos.

### Como funciona

- **`gravai/transcription/base.py`**, função `transcribe_meeting_tracks`, percorre as trilhas da `Session` e manda cada wav via HTTP para um **servidor whisper.cpp** (`POST /inference`, `response_format=verbose_json`, `temperature=0`). O servidor é externo: pode estar no Docker (`docker/docker-compose-whisper.yaml`) ou rodando na máquina (`make exec-whisper`). Endereço em `WHISPER_HOST` e `WHISPER_PORT`.
- Para cada pessoa salva dois arquivos ao lado do wav: `track_<id>_transcription_text.txt` com o texto corrido e `track_<id>_transcription_segments.json` com a lista de segmentos, cada um com `start`, `end`, `text` e `no_speech_prob`.
- Devolve um `TranscriptedSession`, que a API grava como `session_transcription.json`. Esse arquivo é o índice: diz, para cada participante, onde está o JSON de segmentos dele.
- **`gravai/recording/pipeline.py`** (06/10/2026) concentra os três passos que tanto os endpoints antigos de `gravai/api/app.py` quanto os jobs de ata usam: gravar (com o lock de gravação única), fatiar e transcrever. Antes a mesma sequência existia duplicada nos dois lugares; `gravai/transcription/formatter.py`, um utilitário antigo sem uso, foi removido na mesma limpeza.

### Observação sobre custo

Whisper `large-v3-turbo` em CPU leva na casa de dez vezes a duração do áudio e consome bastante RAM. Como cada pessoa vira um wav com a duração da reunião inteira, uma reunião de uma hora com quatro pessoas são quatro horas de áudio para transcrever, mesmo que três quartos de cada arquivo sejam silêncio. Isso é um ponto natural de otimização futura: cortar os trechos silenciosos antes de mandar para o Whisper.

---

## 6. A ponte: normalização da transcrição (`gravai/minutes/transcript_normalizer.py`)

Este é o arquivo que **liga o mundo antigo ao mundo novo**. Ele recebe a pasta de uma gravação e devolve uma lista de `Utterance`, a classe mais importante da Parte 1:

```python
class Utterance(BaseModel):
    speaker: str  # quem falou
    start: float  # segundos desde o início da reunião
    end: float
    text: str  # o que disse
```

Tudo que vem depois, prompt, LLM, docx, só conhece listas de `Utterance`. Não sabe o que é Teams, wav ou Whisper. Isso é o que permite o endpoint `from-transcript` aceitar uma transcrição de qualquer origem.

### O que a normalização faz, em ordem

1. **Carrega os segmentos de cada pessoa.** Usa `session_transcription.json` quando existe. Para gravações antigas, sem esse índice, cai no `gravai/legacy/handle_data/filter_participant_info.py`, que descobre os nomes a partir do `vad_timeline.json`. Se dois participantes têm o mesmo nome de exibição, mantém os dois com o id entre parênteses.
2. **Descarta lixo.** Texto vazio, duração negativa, `no_speech_prob` acima de 0,6 e as alucinações clássicas do Whisper em silêncio: "Legendas pela comunidade Amara.org", "Obrigado por assistir", "[Música]", segmentos só de pontuação. A lista está na constante `HALLUCINATION_PATTERN`.
3. **Ordena tudo por tempo.** Funciona porque todas as trilhas têm a mesma origem de tempo, graças ao truque do volume zero descrito na seção 4.
4. **Remove repetições.** O Whisper, em trechos mudos longos, às vezes repete a mesma frase várias vezes. Frases iguais consecutivas da mesma pessoa viram uma só.
5. **Remove duplicatas por sobreposição.** Quando duas pessoas estavam "falando" ao mesmo tempo segundo a interface, a mesma frase aparece na trilha das duas. A função `_drop_overlap_duplicates` detecta duas falas de pessoas diferentes que se sobrepõem no tempo e têm texto quase igual, e fica só com a mais longa. A atribuição é um palpite. A solução de verdade é a identificação por voz da Parte 2.
6. **Junta turnos.** Segmentos consecutivos da mesma pessoa com pausa de até um segundo viram uma única fala. Isso deixa a transcrição mais parecida com um diálogo e reduz tokens para o LLM.

Tem uma CLI: `uv run python -m gravai.minutes.transcript_normalizer tmp/<sessao>_tracks` imprime a transcrição unificada.

---

## 7. Módulo de geração da ata (`gravai/minutes/`)

Aqui está o coração do TCC. Cinco arquivos, cada um com uma responsabilidade só.

### 7.1 Templates (`gravai/minutes/templates.py` e `gravai/minutes/templates/*.json`)

**Ideia central: um template é um arquivo JSON, não código.** O mesmo JSON alimenta duas coisas, o prompt para o LLM e o layout do `.docx`. Trocar o texto de uma instrução ou adicionar uma seção é editar o JSON, sem mexer em Python.

Um template tem:

- **Metadados**: `id`, `name`, `description`, `title`, `subtitle`, `logo`, `footer`, `language`, `tone`. O `tone` vai literalmente para o prompt.
- **`header`**: campos da tabela de cabeçalho, como projeto, data, horário, número da ata. Todos têm `source: request`, ou seja, **são preenchidos pelo cliente, nunca pelo LLM**. Isso evita que o modelo invente a data da reunião.
- **`participants`**: de onde vem a lista de presentes. Padrão é `transcript`, quem falou. O cliente pode sobrescrever.
- **`sections`**: o corpo da ata, na ordem em que aparece no documento. Cada seção tem `key`, `title`, `type`, `instructions` e flags.

Os cinco tipos de seção e o que o LLM devolve para cada um:

| `type` | O LLM devolve | Exemplo no template Dell |
|---|---|---|
| `paragraph` | um texto | Resumo da reunião |
| `bullets` | lista de textos curtos | Finalizado, Em andamento, Dúvidas |
| `topics` | lista de `{titulo, resumo}` | Tópicos discutidos |
| `table` | lista de linhas com as `columns` | Decisões, Plano de ação |
| `record` | um único objeto com `fields` | Próxima reunião |

Flags que importam: `required` e `allow_empty`. Uma seção `required` com `allow_empty: true` **sempre aparece na ata, mesmo vazia**, e o modelo é instruído a não inventar conteúdo para preenchê-la. `min_items` força um mínimo. `id_prefix` faz o código, e não o LLM, numerar as linhas: D1, D2, A1, A2.

Os quatro templates que existem:

- **`dell.json`**: ata corporativa. Tópicos, resumo com cinco sub-blocos (finalizado, em andamento, ideias, dúvidas, pendências), decisões, plano de ação, próxima reunião. Cabeçalho: projeto, nº, data, horário.
- **`professores.json`**: mesma estrutura, com "feedback dos professores" no lugar de ideias e tom acadêmico. Cabeçalho ganha `professores` e `tipo` (Orientação ou Apresentação).
- **`daily.json`**: curta e informal. Feito, em andamento, ideias, dúvidas, bloqueios, combinados. Participantes numa linha só.
- **`custom.json`**: só o esqueleto. Nome, tom e seções vêm da requisição.

A classe `MinutesTemplate` em `templates.py` é um modelo Pydantic que valida o JSON na carga: tabela sem colunas ou chave de seção duplicada dão erro na hora. `summary()` gera o que o `GET /minutes/templates` devolve para o cliente montar o formulário.

### 7.2 Template personalizado (`gravai/minutes/custom_template.py`)

O cliente pode não querer nenhum dos três modelos fixos. Então manda `template: "custom"` e um objeto `custom` com uma de duas formas:

- **Instruções livres**: "quero um resumo do que foi bom, do que foi ruim e uma lista de ações". Vira uma única seção `paragraph` com essas instruções, e o modelo organiza como achar melhor.
- **Seções declaradas**: uma lista de até 15 seções, cada uma com `key`, `title`, `type`, `instructions` e, quando for tabela, `columns`.

`build_custom_template` pega o esqueleto de `custom.json` e troca nome, tom e seções pelo que veio. O resultado é um `MinutesTemplate` normal. Prompt builder e docx writer nem sabem que foi personalizado.

### 7.3 Montagem do prompt e leitura da resposta (`gravai/minutes/prompt_builder.py`)

Este arquivo faz a tradução nos dois sentidos: template para texto de prompt, e resposta do modelo para dados estruturados.

**Prompt de sistema** (`build_system_prompt`), um por template, com:

1. Papel: "você redige atas a partir de transcrições automáticas, lidas por quem não estava na reunião".
2. Nome do modelo de ata, idioma e tom, vindos do JSON.
3. Oito regras fixas. As mais importantes: usar só o que está na transcrição e deixar vazio o que não foi dito; a transcrição vem de reconhecimento de fala e pode ter erros, então reescrever em texto de ata em vez de copiar; usar os nomes exatamente como na lista de participantes; converter "sexta que vem" em data só quando a data da reunião permitir calcular; não numerar tabelas; responder só JSON.
4. O **formato de saída**: um JSON de exemplo gerado a partir das seções, com uma dica de tipo no lugar de cada valor. Para uma coluna com `values`, a dica é "Pendente | Em andamento | Concluído".
5. A descrição de cada seção, com as `instructions` do template, o mínimo de itens e as regras de cada coluna.

**Prompt de usuário** (`build_user_prompt`), um por requisição, com os dados do cabeçalho, a lista de participantes e a transcrição formatada como `[mm:ss] Nome: texto`. Os tempos ajudam o modelo a ordenar e calcular, mas ele é instruído a não colocá-los na ata.

**Transcrição longa.** `split_transcript` divide a lista de falas em partes de até 24 mil caracteres, mais ou menos 7 mil tokens em português. Quando há mais de uma parte, cada prompt diz "esta é a parte i de n, preencha só com o que aparece aqui", e depois um **prompt de consolidação** (`build_merge_prompt`) recebe os JSONs parciais e pede um JSON final: ordem cronológica, juntar repetidos, versão mais recente vence quando um status muda. Essa é a estratégia "sumariza e depois gera" do desenho do co-orientador, já implementada numa forma simples.

**Leitura da resposta** (`parse_response`). Modelos erram o formato. Então o parser é tolerante: extrai o JSON mesmo que venha dentro de um bloco de código markdown ou com um bloco `<think>`, aceita string onde era lista e lista onde era string, aplica o `default` das colunas, descarta linhas vazias de tabela e numera as linhas com o `id_prefix`. O que ele não perdoa: JSON inválido ou seção obrigatória vazia. Nesses casos lança `ResponseValidationError`, que o orquestrador usa para pedir de novo.

CLI: `uv run python -m gravai.minutes.prompt_builder datasets/reunioes/ES2004a/transcricao.json` imprime os prompts exatos, sem chamar LLM nenhum. É a ferramenta para iterar no prompt.

### 7.4 A camada do LLM (`gravai/minutes/llm.py`)

Um arquivo pequeno de propósito. A função `generate(system, user) -> str` é a única porta para o modelo. Quem chama não sabe qual provedor está por trás. A escolha é a variável `LLM_PROVIDER` no `.env`:

- **`ollama`**: `POST {OLLAMA_HOST}/api/chat` com `format: json`, `temperature: 0` e `num_ctx` configurável. O `num_ctx` existe porque o Ollama usa 2 mil tokens de contexto por padrão e **corta o prompt em silêncio** quando passa disso. Erros de conexão e modelo não baixado viram mensagens claras.
- **`groq`**: reaproveita `gravai/legacy/llm_analyser/groq_config.py`. Existe mas não é o caminho planejado.
- **`fake`**: não chama LLM nenhum. Lê o formato de saída do próprio prompt de sistema e devolve o JSON com texto de exemplo em cada campo. Com isso a API, os jobs, o docx e a página demo rodam de ponta a ponta numa máquina sem GPU. É o modo em que os testes rodam.

**Aqui entra a recomendação do co-orientador**: adicionar provedores online (DeepInfra, OpenAI, Anthropic) nesta função. Como tudo acima só conhece `generate`, o custo é um `if` a mais e algumas variáveis no `.env`.

### 7.5 O orquestrador (`gravai/minutes/generate.py`)

`generate_minutes` é a função que encadeia tudo. Recebe id do template, cabeçalho, lista de falas e caminho de saída, e devolve um `GenerationResult`. Não sabe nada de HTTP. Passo a passo:

1. **Resolve o template**: JSON fixo ou custom construído.
2. **Valida o cabeçalho**: campo obrigatório faltando é `ValueError` antes de gastar qualquer token. Depois limpa e aplica defaults.
3. **Prepara as falas**: descarta vazias, ordena. Lista vazia é `MinutesError("empty_transcript")`.
4. **Define participantes**: os que vieram na requisição ou os falantes distintos da transcrição.
5. **Divide em partes** e, para cada uma, chama `_ask`.
6. **`_ask` é o laço de tentativas.** Chama o LLM, tenta `parse_response`. Se falhar, manda o mesmo prompt de novo com "a resposta anterior foi rejeitada porque X, responda novamente com JSON válido". Isso importa porque com `temperature 0` um modelo repetiria o mesmo erro se o prompt fosse idêntico. Até duas tentativas extras. Depois disso, `MinutesError("llm_invalid_response")`.
7. **Consolida** quando houve mais de uma parte.
8. **Renderiza o docx** e devolve métricas: quantas falas, quantas partes, quantas chamadas ao LLM, quantas repetições, segundos gastos, nome do modelo.

Erros são sempre `MinutesError` com um `code` estável, os mesmos códigos que a API devolve: `llm_unreachable`, `llm_invalid_response`, `empty_transcript`, `transcription_failed`, `recording_failed`, `internal`.

CLI: `uv run python -m gravai.minutes.generate datasets/reunioes/ES2004a/transcricao.json -o ata.docx --json` roda o pipeline inteiro com o LLM do `.env`.

### 7.6 O documento Word (`gravai/minutes/docx_writer.py`)

`write_minutes` recebe template, cabeçalho, participantes e o dicionário já validado, e monta o `.docx` com `python-docx`. O layout segue os PDFs de modelo:

- A4, margens de 2 cm, Arial 10.
- Bloco de título com logo à esquerda quando existe `gravai/minutes/assets/<logo>.png`.
- Tabela de cabeçalho em duas colunas de rótulo e valor, rótulos com fundo cinza.
- Participantes em tabela de três colunas, ou numa linha quando `inline`.
- Cada seção na ordem do template. Seções com o mesmo `group` ficam sob um único título e cada uma ganha uma faixa escura (Dell, professores) ou uma barra lateral (daily).
- Tabelas com cabeçalho escuro e letras brancas, larguras calculadas: a primeira coluna de texto livre fica larga, colunas com formato fixo ou lista de valores ficam estreitas, coluna de ID mais estreita ainda.
- Seção vazia mostra "Nenhum item registrado." em itálico cinza, em vez de sumir.
- Rodapé com o texto do template, `{projeto}` substituído, e número de página à direita.

CLI: `uv run python -m gravai.minutes.docx_writer datasets/reunioes/ES2004a/transcricao.json <minutes.json> -o ata.docx` renderiza uma ata já preenchida (por exemplo o `minutes.json` de uma rodada de experimentos), sem LLM.

---

## 8. Fila de trabalhos (`gravai/jobs/`)

### Por que existe

Gerar uma ata leva de dezenas de segundos a minutos com LLM local. Gravar uma reunião leva a reunião inteira. Nenhum cliente HTTP espera isso numa requisição aberta. Então a API trabalha de forma **assíncrona**: o `POST` cria um job e devolve o id na hora, o cliente consulta o status de tempos em tempos e baixa o arquivo quando terminar. Foi uma das diferenças em relação ao desenho do co-orientador, que mostrava um GET síncrono.

### Os arquivos

- **`gravai/jobs/models.py`**: a classe `Job`. Campos públicos, que a API devolve: `id`, `kind`, `status`, `stage`, `template`, `header`, datas, `result`, `error`. Campos internos: `params` da requisição, `docx_path`, o JSON da ata e os participantes. `status` é `queued`, `running`, `done` ou `failed`. `stage` só existe em `running` e diz em que etapa está: `recording`, `transcribing`, `normalizing`, `generating`, `rendering`.
- **`gravai/jobs/store.py`**: persistência em **SQLite**, uma tabela, colunas JSON para as partes aninhadas. Arquivo em `tmp/minutes_jobs.sqlite3`. Uma conexão só, protegida por lock, porque a API e o worker rodam em threads diferentes. `recover_on_startup` é chamado quando a API sobe: jobs que estavam `running` quando o processo caiu viram `failed` com "interrupted by restart", e jobs ainda `queued` voltam para a fila.
- **`gravai/jobs/worker.py`**: **uma thread** que tira jobs de uma fila e roda um por vez, na ordem de criação. Para cada job busca o executor do seu `kind`, marca `running`, passa uma função `progress` para o executor atualizar o `stage`, e no final grava `done` com o resultado ou `failed` com o erro. A thread nunca morre por exceção.
- **`gravai/jobs/executors.py`**: um executor por tipo de job. Os três terminam na mesma função `_generate`, que chama `generate_minutes` e monta o resultado. A diferença é de onde vêm as falas:
  - `from_transcript`: já vieram na requisição.
  - `from_recording`: roda `normalize_session` numa pasta de gravação já transcrita.
  - `record_and_generate`: grava com `TeamsMeetingRecorder`, fatia e transcreve com `Slicer` e `transcribe_meeting_tracks`, normaliza, gera. As importações pesadas (Playwright) são feitas só dentro dessa função.
- **`gravai/jobs/runtime.py`**: junta store e worker num objeto que fica em `app.state.jobs`. `enqueue` cria o job no banco e avisa o worker.

### O que isso dá

- Jobs e arquivos sobrevivem a reinício da API.
- Um `record_and_generate` em andamento não impede criar outros jobs, só os atrasa.
- Cada job tem pasta própria: `tmp/minutes/<job_id>/ata_<template>_<data>_<projeto>.docx`.

---

## 9. Camada HTTP (`gravai/api/`)

### `gravai/api/app.py`

Cria o FastAPI. No `lifespan`, que roda ao subir e ao descer, abre o servidor WebSocket de áudio e o runtime de jobs. Inclui os dois routers novos. Mantém os endpoints antigos, síncronos, do GravAI original:

- `POST /record_meeting`: grava e, opcionalmente, fatia.
- `POST /transcribe`: fatia e transcreve uma pasta já gravada. Gera `session_metadata.json` e `session_transcription.json`.
- `POST /record_meeting_and_transcribe`: os dois.
- `POST /analyze_transcript`: análise de debate via Groq, código antigo.

Os endpoints são `def`, não `async def`, de propósito: o FastAPI os roda numa thread, então uma gravação de duas horas não trava o resto da API.

### `gravai/api/minutes.py` — os endpoints da ata

Essa é a interface que o SGL, ou qualquer outro cliente, chama. O contrato completo está em `docs/API_MINUTES.md`. Resumo:

| Endpoint | O que recebe | O que faz |
|---|---|---|
| `GET /minutes/templates` | nada | lista os templates com os campos de cabeçalho, para montar o formulário |
| `POST /minutes/templates/draft` | description, name, tone | a IA transforma a descrição da ata em seções (`custom`) para revisar e salvar; síncrono (`minutes/template_draft.py`) |
| `POST /minutes/from-transcript` | template, header, utterances, project_id (opcional) | cria job `from_transcript`, devolve 202 |
| `POST /minutes/from-recording` | template, header, tracks_dir | confere que a pasta tem transcrição, cria job |
| `POST /minutes/record-and-generate` | template, header, meeting_url | confere que é link do Teams e que não há gravação em curso, cria job |
| `GET /minutes/jobs` | limit, status, project_id | últimos jobs, opcionalmente só os de um projeto do SGL |
| `GET /minutes/jobs/{id}` | id | o objeto de job, para polling |
| `POST /minutes/jobs/{id}/stop` | id | o bot sai da reunião; o job segue para transcrição e ata |
| `GET /minutes/jobs/{id}/result` | id | a ata em JSON, antes de virar docx. Útil para pré-visualizar e para avaliar qualidade |
| `GET /minutes/jobs/{id}/download` | id | o `.docx` |

A validação acontece **antes** de criar o job, com Pydantic: template desconhecido, cabeçalho sem campo obrigatório, lista de falas vazia ou `custom` mal formado dão 422 na hora. Erros durante a execução nunca viram 500, viram `status: failed` com um `error.code`.

Desde a versão 1.1 do contrato (23/10/2026), os três `POST` aceitam `project_id`, que o job guarda para o SGL listar as atas de cada projeto. O modelo personalizado de cada projeto fica no SGL e vai no `custom` de cada requisição.

A versão 1.2 (24/10/2026) fecha o fluxo da aba de reunião do SGL (contrato, seção 3.6): `POST /minutes/jobs/{id}/stop` encerra a gravação (`recording/pipeline.request_stop`, que acende um evento lido pelo processo do Playwright a cada segundo); em `record-and-generate`, data e horário vazios são preenchidos com o tempo real da gravação (`minutes/meeting_time.py`, fuso `TIMEZONE`); `callback_url` faz a API avisar o SGL quando o job termina (`jobs/callback.py`, em uma thread separada, três tentativas); e `API_KEY` exige o cabeçalho `X-API-Key` nas rotas de atas e de gravação (`api/security.py`).

### `gravai/api/static/sgl.html` (`/demo/sgl`) — o conteúdo da aba "Reuniões" do SGL

Só o conteúdo da aba de reunião, no tema do SGL (DaisyUI `business`, fonte Figtree), para encaixar na página do projeto que o SGL já tem. Menu lateral, cartão do projeto e as outras abas são do SGL e não são repetidos, para não haver duas versões do que já existe lá. Chama a API real: gravar e encerrar, atas do projeto (ver e Word), editor de modelo personalizado com "Transformar em seções" (`POST /minutes/templates/draft`) e "Salvar como modelo do projeto". O que no SGL ficaria no banco (projetos, títulos das reuniões, modelo de cada projeto) fica no `localStorage` do navegador. Um botão gera a ata a partir de uma reunião do dataset, para demonstrar sem o Teams. Serve de referência visual para o dev do SGL e para a apresentação.

### `gravai/api/demo.py` e `gravai/api/static/demo.html` — o cliente de referência

Como o SGL pode não existir a tempo, a página `/demo` faz o papel dele. É um HTML único, sem framework, que:

1. Carrega `GET /minutes/templates` e monta o formulário de cabeçalho a partir da resposta. Trocar o template redesenha os campos.
2. Tem três abas para a reunião: colar transcrição no formato `[00:12] Ana: texto`, apontar uma pasta de gravação, ou colar link do Teams.
3. Botão "Gerar ata" faz o `POST` certo, faz polling de `GET /jobs/{id}` a cada 5 segundos e mostra o `stage`.
4. Quando termina, mostra métricas, uma pré-visualização da ata seção por seção, o JSON bruto e o botão de download.
5. Lista os últimos jobs.

`gravai/api/demo.py` também serve as reuniões do dataset (`datasets/reunioes/`) como exemplos clicáveis, para demonstração ao vivo.

---

## 10. Configuração e infraestrutura

- **`gravai/config.py`**: classe `Settings` com Pydantic, lê o `.env`. Variáveis novas da Parte 1: `LLM_PROVIDER`, `OLLAMA_HOST`, `OLLAMA_MODEL`, `OLLAMA_NUM_CTX`, `LLM_TIMEOUT_SECONDS`, `JOBS_DB_PATH`. As antigas: `WS_HOST`, `WS_PORT`, `SAVE_DIR`, `WHISPER_HOST`, `WHISPER_PORT`, `RECORDING_DEBUG`, `MAX_RECORDING_SECONDS`.
- **`.env.example`**: modelo comentado do `.env`.
- **`pyproject.toml` + `uv.lock`**: dependências gerenciadas pelo `uv`. Relevantes: `fastapi`, `playwright`, `websockets`, `requests`, `python-docx`, `pytest`.
- **`docker/Dockerfile`**: imagem Python 3.12 com ffmpeg, PortAudio e Chromium do Playwright. **`docker/Dockerfile.whisper`**: compila whisper.cpp e baixa o modelo. **`docker/docker-compose.yaml`** sobe só a API, para quem tem Whisper fora. **`docker/docker-compose-whisper.yaml`** sobe os dois. A pasta `tmp/` é montada do host para dentro do container, então gravações e atas aparecem na máquina.
- **`Makefile`**: atalhos para instalar Playwright, rodar a API, baixar e compilar o whisper.cpp.

---

## 11. Código antigo que continua no repositório

- **`gravai/legacy/llm_analyser/`**: análise retórica de debates com Groq. Chunking, orçamento de tokens, dois passes. Não faz parte da ata, mas emprestou duas funções usadas pelo prompt builder: `chunk_transcript` e `extract_json_from_response`, que estão em `gravai/legacy/llm_analyser/utils.py`.
- **`gravai/legacy/handle_data/filter_participant_info.py`**: lê os JSONs de segmentos de gravações antigas e descobre nomes pelo `vad_timeline.json`. O normalizador usa isso como fallback.

---

## 12. Um pedido de ponta a ponta

O que acontece, na ordem, quando o SGL chama `POST /minutes/record-and-generate` com um link do Teams e o template `professores`:

| Quando | Onde | O que acontece | `status` / `stage` visto pelo cliente |
|---|---|---|---|
| 0 s | `gravai/api/minutes.py` | Valida template, cabeçalho e link. Confere que não há gravação em curso. Cria o job no SQLite e devolve o `id`. | `queued` |
| 0 s | `gravai/jobs/worker.py` | A thread pega o job, marca `running`, chama o executor `run_record_and_generate`. | `running` |
| 0 s a 2 min | `gravai/recording/teams.py` | Abre Chromium, entra no Teams, espera admissão. | `running` / `recording` |
| reunião inteira | `gravai/recording/` | Áudio chega por WebSocket e vai para `track_mainAudio.wav`. Eventos de voz acumulam. | `running` / `recording` |
| fim | `gravai/recording/teams.py` | Detecta fim da reunião, grava `vad_timeline.json`. | |
| +alguns s | `gravai/slicing/slice.py` | Espera o sidecar, calcula janelas de fala, gera um wav por pessoa com ffmpeg. | `running` / `transcribing` |
| +minutos | `gravai/transcription/base.py` | Um `POST /inference` no Whisper por pessoa. Salva os segmentos. | `running` / `transcribing` |
| +1 s | `gravai/minutes/transcript_normalizer.py` | Junta, limpa, ordena. Lista de `Utterance`. | `running` / `normalizing` |
| +30 s a 3 min | `gravai/minutes/generate.py` | Monta prompts, chama o LLM uma vez por parte, consolida se preciso, valida. | `running` / `generating` |
| +1 s | `gravai/minutes/docx_writer.py` | Escreve o `.docx` em `tmp/minutes/<id>/`. | `running` / `rendering` |
| fim | `gravai/jobs/worker.py` | Grava `done`, resultado com `download_url`, métricas e o JSON da ata. | `done` |

Com `from-transcript`, só as três últimas linhas de trabalho acontecem.

---

## 13. O que já está pronto e o que falta

### Pronto e testado

- Bot do Teams gravando e detectando quem fala. Pipeline de fatiamento e transcrição.
- Normalização da transcrição com limpeza de alucinações e duplicatas.
- Quatro templates em JSON com validação. Template personalizado por instruções ou por seções.
- Prompt builder com divisão em partes, consolidação e parser tolerante.
- Camada de LLM com provedor online no formato OpenAI (DeepInfra, Groq, OpenAI...), Ollama local e provedor fake.
- Orquestrador com tentativas e códigos de erro estáveis.
- Renderização em `.docx` fiel aos modelos.
- Jobs assíncronos em SQLite com recuperação após reinício.
- Oito endpoints `/minutes/*` com contrato documentado.
- Página de demonstração funcional.
- Primeiras atas geradas com LLM real (Groq, `gpt-oss-20b` e `qwen3.8-27b`) em 06/10/2026.
- Dataset de 5 reuniões reais do AMI Meeting Corpus traduzidas para pt-BR, com gabarito humano (`datasets/`).
- Runner de experimentos que registra prompt, saída bruta, ata, docx, tempo, tokens e custo por (transcrição, modelo) (`experiments/`).
- 115 testes automatizados que rodam sem LLM, Whisper ou Teams.
- CLIs para cada etapa, para depurar isoladamente.

### Ainda não feito

| O que | Por que importa | Onde encaixa |
|---|---|---|
| **Avaliação manual das atas** (nota 1–5 contra o gabarito) e tabela final | Vira a tabela de resultados do artigo. Pedido do co-orientador. | coluna `nota` em `experiments/results/<rodada>/resumo.csv` |
| **Modelos de 7–8B de verdade** (Llama 3.1 8B, Qwen 2.5 7B, Mistral 7B) | O Groq gratuito só oferece gpt-oss-20b/120b e qwen3.8-27b, com limites apertados por minuto e por dia. Precisa de crédito no DeepInfra (conta criada, sem saldo em 06/10) ou da GPU do laboratório. | `experiments/run_experiments.py --models deepinfra:<modelo>` já funciona |
| **Front para comparar experimentos** ao lado da `/demo` | O co-orientador pediu para ver prompt, entrada e saída de cada teste. Hoje isso está em arquivos (`prompts/NN_*.txt`) por rodada. | `gravai/api/` lendo `experiments/results/` |
| **Reunião real gravada pelo GravAI** no dataset | O dataset atual é traduzido do inglês; não tem erros de ASR em português nem fala sobreposta. Uma reunião real valida isso. | gravar com o bot, normalizar, colocar em `datasets/reunioes/` |
| **Sumarizar antes de gerar** como estratégia alternativa | Hoje a divisão em partes gera JSON parcial por parte e consolida. A alternativa é resumir cada parte em texto e gerar a ata do resumo. Comparar as duas é parte da avaliação. | `gravai/minutes/generate.py` |
| **Entrada por arquivo de áudio único** com corte por silêncio | Para reuniões gravadas fora do bot. Sem o indicador do Teams, precisa de diarização, que é a Parte 2. | novo endpoint `from-audio` e módulo de corte |
| **Lista de pessoas vinda do cliente casada com as vozes** | Parte 2. A API já aceita `participants` opcional. | `POST /speakers` |
| Logos em `gravai/minutes/assets/` | Estético. Sem o arquivo a ata sai sem logo. | colocar `dell.png`, `ufcg.png` |
| Cortar silêncio antes do Whisper | Reduz muito o tempo de transcrição em CPU. | `gravai/slicing/` ou `gravai/transcription/` |
| Autenticação na API | Hoje não há. Deve ficar em rede interna. | `gravai/api/` |

---

## 14. Decisões de projeto e o motivo de cada uma

- **API assíncrona com polling** em vez de resposta direta. Porque gerar leva minutos e gravar leva horas. Nenhum cliente PHP, nem navegador, espera isso numa conexão aberta.
- **Templates em JSON, não em código.** Mudar a ata não exige programador. E o mesmo arquivo garante que o prompt e o documento concordam sobre quais seções existem.
- **Cabeçalho vem do cliente, nunca do LLM.** Data, projeto e número são fatos que o sistema já sabe. Deixar o modelo preencher é convidar erro.
- **Seção vazia é permitida e aparece como vazia.** A alternativa seria o modelo inventar conteúdo para preencher. O prompt diz isso explicitamente e o parser respeita.
- **Numeração de tabelas no código.** Modelos pulam ou repetem números. Gerar D1, D2 depois é trivial e sempre certo.
- **Temperatura zero e retry com feedback.** Reprodutibilidade para a avaliação. E quando a resposta falha, o novo prompt diz por que, senão o modelo repetiria a mesma coisa.
- **Trilha por pessoa com volume zero em vez de corte.** Mantém a origem de tempo igual em todas as trilhas, o que faz a ordenação cronológica funcionar sem alinhamento.
- **Provedor fake.** Permitiu construir e testar toda a camada de API e de documento sem ter GPU. É o motivo de haver 98 testes verdes antes de qualquer chamada real a um LLM.
- **Uma única função `generate(system, user)` como porta para o LLM.** Trocar de provedor, ou comparar vários, é mexer num lugar só.
- **Página demo em vez de esperar o SGL.** O produto do TCC é a API. A página prova que ela é usável por um cliente externo e serve de referência para quem for integrar.

---

## 15. Como rodar e testar hoje

```bash
# dependências
uv sync

# testes (sem LLM, Whisper ou Teams)
uv run pytest

# API com o provedor fake e página demo em http://localhost:8000/demo
LLM_PROVIDER=fake uv run fastapi dev gravai/api/app.py

# ver o prompt exato que um template gera
uv run python -m gravai.minutes.prompt_builder datasets/reunioes/ES2004a/transcricao.json

# pipeline completo pela linha de comando, com o LLM do .env
uv run python -m gravai.minutes.generate datasets/reunioes/ES2004a/transcricao.json -o ata.docx --json

# só o docx, a partir de uma ata já preenchida
uv run python -m gravai.minutes.docx_writer datasets/reunioes/ES2004a/transcricao.json experiments/results/<rodada>/<par>/minutes.json -o ata.docx

# juntar a transcrição de uma gravação real
uv run python -m gravai.minutes.transcript_normalizer tmp/<sessao>_tracks
```

---

## 16. Glossário rápido

- **Utterance**: uma fala. Quem, de quando até quando, o quê. A unidade básica de toda a Parte 1.
- **Track / trilha**: um arquivo wav. `mainAudio` é a reunião inteira; `track_<id>` é uma pessoa.
- **VAD**: detecção de atividade de voz. Aqui, feita a partir da interface do Teams, não do áudio.
- **Sidecar**: `session_sidecar.json`, metadados de início e fim das trilhas.
- **Template**: o JSON que descreve uma ata.
- **Seção**: um bloco da ata. Parágrafo, lista, tópicos, tabela ou registro.
- **Job**: um pedido de ata na fila. Tem id, status, etapa e resultado.
- **Executor**: a função que roda um tipo de job.
- **Provedor**: quem responde ao prompt. Ollama, Groq, fake, e em breve os online.
- **Parte / consolidação**: divisão de transcrição longa em pedaços e o prompt final que junta os JSONs parciais.
- **Transcrição do dataset**: arquivo `datasets/reunioes/<id>/transcricao.json` com template, cabeçalho e falas, no mesmo formato do corpo de `from-transcript`. Os testes usam a reunião ES2004a.
