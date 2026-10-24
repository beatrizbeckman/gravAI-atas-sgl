# GravAI — API de geração de atas (`/minutes/*`)

Contrato HTTP para gerar atas de reunião (`.docx`) a partir de transcrições ou gravações feitas pelo GravAI. Este documento é a referência para qualquer cliente da API: a página de demonstração do próprio GravAI, o SGL ou um script.

Versão do contrato: **1.2** (24/10/2026). Mudanças incompatíveis sobem a versão principal (2.0); acréscimos que não quebram clientes antigos sobem a secundária. Implementado em `gravai/api/minutes.py`; o Swagger em `/docs` mostra os schemas exatos.

| Versão | O que mudou |
|---|---|
| 1.0 (01/10/2026) | Primeira versão: templates, três formas de criar job, acompanhamento e download. |
| 1.1 (23/10/2026) | `project_id` opcional nos jobs e filtro `GET /minutes/jobs?project_id=` (3, 3.5, 4.1, 4.5); LLM online como padrão (Groq, `openai/gpt-oss-120b`). Nada que funcionava na 1.0 mudou. |
| 1.2 (24/10/2026) | Fluxo da aba de reunião do SGL (3.6): encerrar a gravação (`POST /minutes/jobs/{id}/stop`, 4.6), data e horário preenchidos pela gravação (3.3), aviso de conclusão por webhook (`callback_url`, 4.7) e chave de acesso opcional (`X-API-Key`, 1.1). Com `API_KEY` vazio, nada que funcionava na 1.1 mudou. |

---

## 1. Visão geral

Gerar uma ata é lento (de alguns segundos a vários minutos, conforme o LLM e os limites do provedor; horas quando inclui gravar a reunião). Por isso a API é **assíncrona**: cada `POST` cria um *job*, devolve o `job_id` imediatamente e o cliente consulta o status até ele terminar.

```
cliente ──POST /minutes/from-transcript──► API  (202 Accepted, {"id": "..."} )
cliente ──GET  /minutes/jobs/{id}────────► API  (status: queued → running → done | failed)
cliente ──GET  /minutes/jobs/{id}/download► API  (arquivo .docx)
```

Três maneiras de criar um job, da mais simples à mais completa:

| Endpoint | Entrada | Faz |
|---|---|---|
| `POST /minutes/from-transcript` | transcrição já pronta (lista de falas) | LLM → `.docx` |
| `POST /minutes/from-recording` | pasta de uma gravação já transcrita pelo GravAI | normaliza transcrição → LLM → `.docx` |
| `POST /minutes/record-and-generate` | link de reunião do Teams | grava → transcreve → normaliza → LLM → `.docx` |

Base URL de desenvolvimento: `http://localhost:8000`. Todos os corpos são JSON em UTF-8. Datas e horas em texto, no formato que vai aparecer na ata (a API não converte).

### 1.1 Chave de acesso

Quando o servidor tem `API_KEY` configurada (seção 7), toda chamada a `/minutes/*` e às rotas de gravação (`/record_meeting`, `/transcribe`, `/record_meeting_and_transcribe`, `/analyze_transcript`) precisa do cabeçalho:

```
X-API-Key: <a chave combinada>
```

Sem ele, ou com a chave errada → `401`. A chave fica **no servidor do SGL** (nunca no JavaScript de uma página, onde qualquer um a leria). A página `/demo`, o Swagger (`/docs`) e o contrato (`/openapi.json`) continuam abertos; a `/demo` pede a chave na primeira resposta `401` e a guarda só na aba aberta. Com `API_KEY` vazia (padrão), nenhuma chave é pedida.

---

## 2. Templates

### `GET /minutes/templates`

Lista os modelos de ata disponíveis e os campos de cabeçalho que cada um espera. Serve para o cliente montar o formulário sem conhecer os templates de antemão.

**Resposta `200`**

```json
{
  "templates": [
    {
      "id": "dell",
      "name": "Ata Dell",
      "description": "Reunião com Dell Technologies. Tópicos, resumo, decisões, plano de ação e próxima reunião.",
      "header": [
        {"key": "projeto", "label": "Projeto", "required": true,  "format": null,          "values": null, "default": null},
        {"key": "numero",  "label": "Ata nº",  "required": false, "format": "000",         "values": null, "default": null},
        {"key": "data",    "label": "Data",    "required": true,  "format": "DD/MM/AAAA",  "values": null, "default": null},
        {"key": "horario", "label": "Horário", "required": false, "format": "HH:MM – HH:MM", "values": null, "default": null}
      ],
      "participants": {"source": "transcript", "label": "Participantes"},
      "sections": [
        {"key": "topicos",   "title": "TÓPICOS DISCUTIDOS", "type": "topics",    "columns": []},
        {"key": "resumo",    "title": "RESUMO DA REUNIÃO",  "type": "paragraph", "columns": []},
        {"key": "decisoes",  "title": "DECISÕES",           "type": "table", "columns": [{"key": "id", "label": "Nº"}, {"key": "decisao", "label": "Decisão"}, {"key": "aprovada_por", "label": "Aprovada por"}]},
        {"key": "plano_acao","title": "PLANO DE AÇÃO",      "type": "table", "columns": [{"key": "id", "label": "ID"}, {"key": "acao", "label": "Ação / Entregável"}, {"key": "responsavel", "label": "Responsável"}, {"key": "prazo", "label": "Prazo"}, {"key": "status", "label": "Status"}]}
      ]
    },
    {"id": "professores", "...": "..."},
    {"id": "daily", "...": "..."},
    {"id": "custom", "name": "Ata personalizada", "description": "Seções e tom definidos na requisição (campo custom).", "header": ["..."], "sections": []}
  ]
}
```

Campos de cabeçalho por template (fonte: `gravai/minutes/templates/*.json`):

| Template | Campos (`*` = obrigatório) |
|---|---|
| `dell` | `projeto*`, `numero`, `data*`, `horario` |
| `professores` | `projeto*`, `numero`, `data*`, `horario`, `professores*`, `tipo` (`Orientação` \| `Apresentação`, padrão `Orientação`) |
| `daily` | `projeto*`, `data*` (formato `DD/MM/AAAA · HH:MM – HH:MM`) |
| `custom` | `projeto*`, `data*`, `horario` |

O cabeçalho é **sempre** preenchido pelo cliente, nunca pelo LLM. `format` é só uma dica de exibição; a API grava o texto como veio.

---

## 3. Criar jobs

Os três `POST` compartilham o bloco de **especificação da ata**:

```json
{
  "template": "dell",
  "header": {"projeto": "Portal de Suporte", "numero": "007", "data": "29/09/2026", "horario": "14:00 – 14:45"},
  "project_id": "sgl-42",
  "participants": ["Ana", "Bruno", "Carla", "Diego"],
  "custom": null,
  "callback_url": "https://sgl.lab/api/atas/webhook"
}
```

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `template` | string | sim | `dell`, `professores`, `daily` ou `custom`. |
| `header` | objeto | sim | Chaves conforme `GET /minutes/templates`. Faltando campo obrigatório → `422`. Chaves desconhecidas são ignoradas. |
| `project_id` | string (1 a 100 caracteres) | não | Identificador do projeto no sistema cliente (no SGL, o id do projeto). A API não interpreta: só guarda no job e permite listar por ele (4.5). Omitido → `null`. Ver 3.5. |
| `participants` | lista de strings | não | Nomes a listar na ata. Quando omitido, a API usa os falantes da transcrição. Quando informado, substitui a lista da transcrição **só na seção de participantes**; os nomes dentro do texto continuam sendo os da transcrição. |
| `custom` | objeto | só quando `template = "custom"` | Ver 3.4. |
| `callback_url` | URL `http`/`https` | não | Para onde a API faz um `POST` com o job quando ele terminar (`done` ou `failed`). Ver 4.7. |

### 3.1 `POST /minutes/from-transcript`

Caminho principal. O cliente já tem a transcrição (de uma gravação anterior do GravAI, de outro sistema ou digitada) e quer só a ata.

**Corpo**

```json
{
  "template": "dell",
  "header": {"projeto": "Portal de Suporte", "numero": "007", "data": "29/09/2026", "horario": "14:00 – 14:45"},
  "participants": null,
  "utterances": [
    {"speaker": "Carla", "start": 0.0,  "end": 9.5,  "text": "Boa tarde pessoal, vamos começar..."},
    {"speaker": "Ana",   "start": 10.0, "end": 14.0, "text": "Boa tarde Carla. Antes disso..."}
  ]
}
```

| Campo | Tipo | Regras |
|---|---|---|
| `utterances` | lista | Mínimo 1 item. Ordem cronológica (a API reordena por `start` se vier fora de ordem). |
| `utterances[].speaker` | string | Nome exatamente como deve aparecer na ata. |
| `utterances[].start`, `end` | número (segundos) | `end > start`. Contados do início da reunião. Só servem de orientação ao modelo; não entram na ata. |
| `utterances[].text` | string | Texto da fala. Vazio é descartado. |

**Resposta `202 Accepted`**: o objeto de job (seção 4) com `status: "queued"`.

### 3.2 `POST /minutes/from-recording`

Para uma reunião que o GravAI já gravou e transcreveu (`POST /transcribe` do GravAI gerou `session_transcription.json` na pasta).

**Corpo**

```json
{
  "template": "professores",
  "header": {"projeto": "TCC GravAI", "data": "29/09/2026", "professores": "Prof. Fulano"},
  "tracks_dir": "./tmp/5d3136ef-0d7f-4664-a8d8-28ecc6b4929e_tracks"
}
```

| Campo | Regras |
|---|---|
| `tracks_dir` | Pasta `*_tracks` de uma gravação, relativa à raiz do GravAI ou absoluta. Deve conter `session_transcription.json` ou os arquivos `track_*_transcription_segments.json` + `vad_timeline.json`. Pasta inexistente → `404`. Pasta sem transcrição → `422`. |

A API roda a normalização da transcrição (junta as tracks de cada participante, remove alucinações e duplicatas) e segue como em 3.1.

### 3.3 `POST /minutes/record-and-generate`

Fluxo completo: o bot entra na reunião, grava até ela acabar, transcreve, normaliza e gera a ata. O job fica em `running` por toda a reunião.

**Corpo**

```json
{
  "template": "daily",
  "header": {"projeto": "GravAI", "data": "01/10/2026 · 09:00 – 09:15"},
  "meeting_url": "https://teams.live.com/meet/...",
  "max_recording_seconds": 7200
}
```

| Campo | Regras |
|---|---|
| `meeting_url` | Link do Teams (`teams.live.com` ou `teams.microsoft.com`). Outro domínio → `400`. |
| `max_recording_seconds` | Opcional, mínimo 60. Teto de segurança caso o fim da reunião não seja detectado. Padrão: `MAX_RECORDING_SECONDS` do servidor (7200). |

**Fim da gravação.** O bot sai da reunião quando o Teams mostra que ela acabou ou que ele foi removido, quando o cliente pede (`POST /minutes/jobs/{id}/stop`, 4.6) ou quando `max_recording_seconds` estoura. O que foi gravado segue para transcrição e ata nos três casos.

**Data e horário pela gravação.** Só nesta rota, os campos de cabeçalho cujo `format` é `DD/MM/AAAA`, `HH:MM – HH:MM` ou `DD/MM/AAAA · HH:MM – HH:MM` podem ser omitidos ou enviados vazios: a API preenche com o momento em que o bot entrou e saiu da reunião, no fuso `TIMEZONE` do servidor. Ex.: no `dell`, `{"projeto": "X"}` vira `{"projeto": "X", "data": "24/10/2026", "horario": "10:05 – 11:10"}`. Campo enviado pelo cliente nunca é sobrescrito. O cabeçalho final aparece no job (`header`) e na ata.

Só **uma gravação por vez**: se já houver um job `record_and_generate` gravando **ou ainda na fila**, a resposta é `409` com `detail` explicando. Jobs dos outros tipos não têm essa restrição.

### 3.4 Ata personalizada (`template = "custom"`)

O cliente descreve a ata em vez de escolher um modelo fixo. Duas formas, excludentes:

**(a) Instruções livres** — o LLM organiza o conteúdo como achar melhor, em uma única seção de texto:

```json
{
  "template": "custom",
  "header": {"projeto": "Sprint 12", "data": "01/10/2026"},
  "custom": {
    "name": "Ata de retrospectiva",
    "tone": "Informal, direto, sem jargão.",
    "instructions": "Quero um resumo do que foi bom, do que foi ruim e uma lista de ações para a próxima sprint."
  },
  "utterances": ["..."]
}
```

**(b) Seções declaradas** — o cliente define a estrutura e o LLM preenche cada seção:

```json
{
  "template": "custom",
  "header": {"projeto": "Sprint 12", "data": "01/10/2026"},
  "custom": {
    "name": "Ata de retrospectiva",
    "tone": "Informal, direto.",
    "sections": [
      {"key": "bom",   "title": "O que foi bom",  "type": "bullets",   "instructions": "Pontos positivos citados pelo time."},
      {"key": "ruim",  "title": "O que foi ruim", "type": "bullets",   "instructions": "Problemas citados.", "allow_empty": true},
      {"key": "acoes", "title": "Ações",          "type": "table",     "instructions": "Tarefas com dono.",
       "columns": [{"key": "acao", "label": "Ação"}, {"key": "quem", "label": "Quem"}, {"key": "prazo", "label": "Prazo", "format": "DD/MM"}]}
    ]
  },
  "utterances": ["..."]
}
```

| Campo de `custom` | Regras |
|---|---|
| `name` | Opcional. Nome do modelo mostrado no prompt. Padrão: "Ata personalizada". |
| `title`, `subtitle` | Opcionais. Título e subtítulo impressos no `.docx`. Padrão: "ATA DE REUNIÃO". |
| `tone` | Opcional. Padrão: formal, terceira pessoa. |
| `instructions` | Forma (a). String não vazia. |
| `sections` | Forma (b). Lista com 1 a 15 seções. |
| `sections[].key` | Obrigatório, único, `snake_case` (`^[a-z][a-z0-9_]*$`). |
| `sections[].title` | Obrigatório. |
| `sections[].type` | `paragraph`, `bullets`, `topics`, `table` ou `record`. |
| `sections[].instructions` | Obrigatório. O que o LLM deve colocar ali. |
| `sections[].allow_empty` | Opcional, padrão `true` (seção aparece mesmo vazia; o modelo não inventa). |
| `sections[].columns` / `fields` | Obrigatório para `table` / `record`. Cada item: `key`, `label`, e opcionalmente `format`, `values`, `default`, `instructions`. |

Mandar `instructions` e `sections` juntos, ou nenhum dos dois → `422`.

### 3.5 Uso por projeto (SGL)

No SGL cada projeto tem as suas atas e pode ter o seu modelo de ata. A divisão de responsabilidades:

| Quem | Guarda / faz |
|---|---|
| **SGL** | Cadastro dos projetos, quem pode ver o quê, e o modelo de ata escolhido por projeto: o id de um template fixo (`dell`, `professores`, `daily`) ou o objeto `custom` completo (3.4), salvo no banco do SGL. |
| **API** | Gera a ata, guarda o job com o `project_id` recebido e lista os jobs por projeto. Não guarda projetos nem modelos personalizados. |

Fluxo:

1. Usuário abre o projeto `sgl-42` no SGL. O SGL lista as atas dele com `GET /minutes/jobs?project_id=sgl-42&status=done`.
2. Usuário pede uma ata nova. O SGL monta o corpo com o template do projeto (ou o `custom` salvo), o cabeçalho e `"project_id": "sgl-42"`, e chama um dos `POST` de 3.1 a 3.3.
3. O SGL acompanha o job (4.2) e oferece o download (4.3) quando terminar.

O modelo personalizado vai **inteiro em cada requisição**: assim a API não tem uma segunda cópia que possa ficar diferente da que está no SGL, e mudar o modelo de um projeto não exige nenhuma chamada extra.

### 3.6 Fluxo da aba de reunião do SGL

O caso principal da integração: na aba de reunião de um projeto, o usuário escolhe o modelo de ata, inicia a reunião, o bot grava e transcreve, e no fim a ata aparece no SGL. O passo a passo do lado do SGL (banco, cliente HTTP, controller, webhook, aba em React e testes) está em [`docs/INTEGRACAO_SGL.md`](INTEGRACAO_SGL.md).

```
Usuário (SGL)            Servidor do SGL                          API GravAI
─────────────            ───────────────                          ──────────
abre a aba de reunião ─► GET  /minutes/templates ───────────────► lista de modelos (cache: muda pouco)
escolhe modelo, cola
o link do Teams,
"Iniciar reunião" ─────► POST /minutes/record-and-generate ─────► 202 job (queued)
                         { template | custom, header: {projeto},
                           meeting_url, project_id, callback_url }
                         guarda job.id na reunião do SGL
                                                                   bot entra (admitir na sala de espera)
mostra a etapa ◄──────── GET  /minutes/jobs/{id} a cada 30 s ────► running · recording
"Encerrar reunião" ────► POST /minutes/jobs/{id}/stop ───────────► 202; o bot sai
                                                                   running · transcribing → generating → rendering
                         POST callback_url ◄────────────────────── job done (ou failed)
mostra a ata ◄────────── GET  /minutes/jobs/{id}/result ─────────► seções em JSON
"Baixar Word" ─────────► GET  /minutes/jobs/{id}/download ───────► .docx
```

Pontos de atenção:

1. **Chamadas pelo servidor do SGL.** Quem chama a API é o PHP do SGL, que guarda a chave. A API não aceita chamadas feitas pelo JavaScript de páginas de outro endereço (não há CORS), e a chave nunca deve ir para o navegador.
2. **O SGL guarda o `job.id`** na reunião dele. É por esse id que acompanha, encerra e baixa; o `project_id` serve para listar as atas do projeto.
3. **Cabeçalho mínimo:** `projeto` (e os obrigatórios do modelo que não são data/hora, como `professores` no template `professores`). Data e horário vêm da gravação (3.3).
4. **Admissão do bot.** O bot entra como convidado e pode ficar na sala de espera do Teams; alguém precisa admiti-lo. O job fica em `running · recording` desde que o bot começa a entrar.
5. **Acompanhar ou ser avisado.** Com `callback_url`, o SGL não precisa consultar até o fim: recebe o job pronto (4.7). Mesmo assim, consultar a cada 30 s enquanto a aba estiver aberta mostra a etapa ao usuário e serve de reserva se o aviso falhar.
6. **Uma reunião por vez** no servidor (3.3): enquanto uma grava, outra tentativa recebe `409`; o SGL deve mostrar "o gravador está ocupado, tente mais tarde".
7. **Revisão.** A ata é um rascunho gerado por IA: o SGL deve deixar claro que precisa de revisão antes de ser distribuída (seção 8).

---

## 4. Acompanhar jobs

### 4.1 Objeto de job

Todas as respostas que envolvem job têm este formato:

```json
{
  "id": "6f1c2a0e-3b7d-4a7e-9f2a-0c1d2e3f4a5b",
  "kind": "from_transcript",
  "status": "done",
  "stage": null,
  "template": "dell",
  "header": {"projeto": "Portal de Suporte", "numero": "007", "data": "29/09/2026", "horario": "14:00 – 14:45"},
  "project_id": "sgl-42",
  "created_at": "2026-10-01T14:03:12Z",
  "updated_at": "2026-10-01T14:04:40Z",
  "finished_at": "2026-10-01T14:04:40Z",
  "result": {
    "download_url": "/minutes/jobs/6f1c2a0e-3b7d-4a7e-9f2a-0c1d2e3f4a5b/download",
    "filename": "ata_dell_2026-10-01_portal-de-suporte.docx",
    "participants": ["Ana", "Bruno", "Carla", "Diego"],
    "utterances": 27,
    "parts": 1,
    "llm_model": "openai/gpt-oss-120b",
    "generation_seconds": 84.3
  },
  "error": null
}
```

| Campo | Descrição |
|---|---|
| `id` | UUID do job. |
| `kind` | `from_transcript`, `from_recording` ou `record_and_generate`. |
| `status` | `queued` (na fila), `running` (executando), `done` (ata pronta), `failed` (erro; ver `error`). |
| `stage` | Só quando `running`: `recording`, `transcribing`, `normalizing`, `generating` (LLM), `rendering` (docx). `null` nos outros status. |
| `template`, `header`, `project_id` | Ecos da requisição (`project_id` é `null` quando não foi enviado). |
| `created_at`, `updated_at`, `finished_at` | ISO 8601 em UTC. `finished_at` é `null` até `done`/`failed`. |
| `result` | `null` até `done`. `parts` é em quantas partes a transcrição foi dividida para o LLM (1 = coube de uma vez; partes de cerca de 24 mil caracteres). |
| `error` | `null` exceto em `failed`. Objeto `{"code": "...", "message": "..."}`. |

Códigos de `error.code`:

| `code` | Significado | O que o cliente faz |
|---|---|---|
| `llm_unreachable` | O LLM não respondeu ou recusou a chamada: provedor online fora do ar, chave ausente ou inválida, sem saldo (402), limite de uso (429) mesmo após as novas tentativas, tempo esgotado; ou servidor Ollama fora do ar / modelo não baixado. `message` traz o motivo. | Avisar o operador; tentar de novo mais tarde. |
| `llm_invalid_response` | O modelo não devolveu JSON válido ou deixou seção obrigatória vazia, mesmo após as tentativas. | Tentar de novo; se persistir, revisar a transcrição (muito curta ou sem conteúdo). |
| `empty_transcript` | Após a normalização não sobrou nenhuma fala. | Checar a gravação/transcrição. |
| `transcription_failed` | Whisper falhou ou não respondeu. | Avisar o operador. |
| `recording_failed` | Bot não entrou na reunião, foi rejeitado ou removido. | Checar o link e se o bot foi admitido. |
| `internal` | Qualquer outro erro. `message` tem o detalhe. | Reportar. |

### 4.2 `GET /minutes/jobs/{id}`

Devolve o objeto de job. `404` se o id não existe.

**Polling recomendado:** a cada **5 s** para `from_transcript` e `from_recording`; a cada **30 s** para `record_and_generate` (que dura a reunião inteira). Parar quando `status` for `done` ou `failed`.

Duração típica com o padrão (Groq gratuito, `openai/gpt-oss-120b`): de 2 a 11 min para as reuniões do dataset, quase tudo esperando o limite de uso por minuto do provedor (a geração em si leva de 8 a 52 s). Com LLM local 7B em GPU, 30 s a 3 min para 1 h de reunião; em CPU, multiplique por 10.

### 4.3 `GET /minutes/jobs/{id}/download`

Devolve o `.docx` (`Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document`, `Content-Disposition: attachment; filename="..."`).

- `404`: job não existe.
- `409`: job ainda não terminou (`status` ≠ `done`) ou falhou.

### 4.4 `GET /minutes/jobs/{id}/result`

Devolve o **conteúdo da ata em JSON**, no formato das seções do template, antes de virar `.docx`. Útil para pré-visualizar na tela ou para avaliação da qualidade.

```json
{
  "template": "dell",
  "header": {"..."},
  "participants": ["Ana", "Bruno", "Carla", "Diego"],
  "minutes": {
    "topicos": [{"titulo": "Integração com a API de chamados", "resumo": "..."}],
    "resumo": "Reunião de acompanhamento do projeto...",
    "finalizado": ["..."],
    "em_andamento": ["..."],
    "ideias_propostas": [],
    "duvidas": ["..."],
    "pendencias": ["..."],
    "decisoes":   [{"id": "D1", "decisao": "...", "aprovada_por": "Carla"}],
    "plano_acao": [{"id": "A1", "acao": "...", "responsavel": "Carla", "prazo": "02/10", "status": "Pendente"}],
    "proxima_reuniao": {"data": "06/10/2026", "horario": "14:00", "pauta": "..."}
  }
}
```

Formato de cada valor conforme o `type` da seção: `paragraph` → string; `bullets` → lista de strings; `topics` → lista de `{titulo, resumo}`; `table` → lista de objetos com as colunas (+ `id` quando o template numera); `record` → objeto com os campos. Mesmos códigos de erro de 4.3.

### 4.5 `GET /minutes/jobs`

Lista os jobs mais recentes, do mais novo para o mais antigo. Query, todos opcionais e combináveis:

| Parâmetro | Descrição |
|---|---|
| `limit` | Padrão 20, máximo 100. |
| `status` | `queued`, `running`, `done` ou `failed`. |
| `project_id` | Só os jobs criados com esse `project_id` (3.5). Jobs sem projeto só aparecem na listagem sem esse filtro. |

Exemplo: `GET /minutes/jobs?project_id=sgl-42&status=done&limit=50`.

### 4.6 `POST /minutes/jobs/{id}/stop`

O botão "Encerrar reunião": o bot sai do Teams e o job continua normalmente (transcrição, ata). Sem corpo. Responde `202` com o objeto de job (ainda em `running · recording`; a etapa muda nos segundos seguintes).

- `404`: job não existe.
- `409`: o job não está gravando (outro tipo, ainda na fila, ou já em outra etapa), ou o bot ainda está abrindo o Teams; neste caso, tentar de novo em alguns segundos.

O pedido é atendido quando o bot já está dentro da reunião (ele confere a cada segundo). Se ainda estiver na sala de espera, sai assim que for admitido.

### 4.7 Aviso de conclusão (`callback_url`)

Quando um job criado com `callback_url` termina (`done` ou `failed`), a API faz:

```
POST <callback_url>
Content-Type: application/json
X-API-Key: <API_KEY do servidor, quando configurada>

{ ...objeto de job (4.1)... }
```

- O receptor deve responder `2xx` em até 10 s e processar depois, se for demorado. Sem `2xx`, a API tenta mais duas vezes (após 2 s e 10 s) e desiste.
- O `X-API-Key` permite ao SGL confirmar que o aviso veio da API: comparar com a chave combinada e recusar se for diferente.
- Tratar o aviso pelo `id` do job, sem supor que chega exatamente uma vez: se a resposta do SGL se perder, o mesmo job pode chegar de novo.
- Jobs interrompidos por reinício da API (`internal`, "interrupted by restart") não geram aviso. Para não perder nenhum, o SGL pode conferir de tempos em tempos os jobs que ainda não recebeu (`GET /minutes/jobs?project_id=...`).
- O aviso não é enviado para jobs sem `callback_url`.

```json
{"jobs": [{"...objeto de job..."}, {"..."}]}
```

---

## 5. Erros síncronos (nas respostas HTTP)

Formato padrão do FastAPI:

```json
{"detail": "mensagem"}
```

Em `422` o `detail` é a lista de erros de validação do FastAPI (campo, mensagem).

| Status | Quando |
|---|---|
| `400` | `meeting_url` não é do Teams. |
| `401` | `API_KEY` configurada no servidor e cabeçalho `X-API-Key` ausente ou errado (1.1). |
| `404` | Job inexistente; `tracks_dir` inexistente. |
| `409` | Já há uma gravação em andamento; download/result de job não concluído; `stop` em job que não está gravando. |
| `422` | Corpo ou query inválidos: template desconhecido, campo obrigatório do cabeçalho ausente, `utterances` vazia, `custom` mal formado, `project_id` vazio ou com mais de 100 caracteres, `callback_url` que não é `http`/`https`, pasta sem transcrição. |
| `500` | Erro inesperado ao **criar** o job (erros durante a execução vão para `status: failed`, nunca para `500`). |

---

## 6. Exemplos com `curl`

```bash
# 1. Descobrir templates e campos
curl http://localhost:8000/minutes/templates

# 2. Criar um job a partir de uma transcrição (fixture do repositório)
curl -X POST http://localhost:8000/minutes/from-transcript \
  -H "Content-Type: application/json" \
  -d @datasets/reunioes/ES2004a/transcricao.json
# → 202 {"id": "6f1c...", "status": "queued", ...}

# 3. Consultar
curl http://localhost:8000/minutes/jobs/6f1c2a0e-3b7d-4a7e-9f2a-0c1d2e3f4a5b

# 4. Baixar quando status = done
curl -OJ http://localhost:8000/minutes/jobs/6f1c2a0e-3b7d-4a7e-9f2a-0c1d2e3f4a5b/download

# 5. Atas de um projeto (SGL): criar com project_id e listar só as dele
curl -X POST http://localhost:8000/minutes/from-transcript \
  -H "Content-Type: application/json" \
  -d '{"project_id":"sgl-42","template":"daily","header":{"projeto":"GravAI","data":"23/10/2026 · 09:00 – 09:15"},"utterances":[{"speaker":"Ana","start":0,"end":5,"text":"Ontem terminei o filtro por projeto."}]}'
curl "http://localhost:8000/minutes/jobs?project_id=sgl-42"

# 6. Gravação já transcrita
curl -X POST http://localhost:8000/minutes/from-recording \
  -H "Content-Type: application/json" \
  -d '{"template":"daily","header":{"projeto":"GravAI","data":"01/10/2026 · 09:00 – 09:15"},"tracks_dir":"./tmp/5d3136ef-0d7f-4664-a8d8-28ecc6b4929e_tracks"}'

# 7. Aba de reunião do SGL (3.6), com chave de acesso
KEY="a chave do .env do servidor"
curl -X POST http://localhost:8000/minutes/record-and-generate \
  -H "Content-Type: application/json" -H "X-API-Key: $KEY" \
  -d '{"project_id":"sgl-42","template":"dell","header":{"projeto":"Portal de Suporte"},"meeting_url":"https://teams.live.com/meet/...","callback_url":"https://sgl.lab/api/atas/webhook"}'
# → 202 {"id": "6f1c...", "status": "queued", ...}; admitir o bot no Teams
curl -X POST -H "X-API-Key: $KEY" http://localhost:8000/minutes/jobs/6f1c2a0e-3b7d-4a7e-9f2a-0c1d2e3f4a5b/stop
```

> Os arquivos `datasets/reunioes/<id>/transcricao.json` têm exatamente o formato do corpo de `from-transcript` (mais um campo `meta`, ignorado pela API) e servem de exemplo de requisição.

Exemplo de polling em JavaScript (página de demonstração):

```js
async function waitForJob(id) {
  while (true) {
    const job = await (await fetch(`/minutes/jobs/${id}`)).json();
    if (job.status === "done" || job.status === "failed") return job;
    await new Promise(r => setTimeout(r, 5000));
  }
}
```

---

## 7. Configuração do servidor que afeta o cliente

| Variável (`.env`) | Efeito visível |
|---|---|
| `LLM_PROVIDER` | Quem gera a ata: `openai_compatible` (padrão, API online no formato da OpenAI), `ollama` (local) ou `fake` (texto marcador, sem LLM; só para demonstrar a estrutura). |
| `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` | Provedor e modelo online. Padrão: Groq (`https://api.groq.com/openai/v1`) com `openai/gpt-oss-120b`. O modelo aparece em `result.llm_model`. |
| `LLM_MAX_TOKENS` | Teto da resposta do provedor online (padrão 8000; modelos que raciocinam gastam parte dele antes de responder). |
| `OLLAMA_HOST`, `OLLAMA_MODEL`, `OLLAMA_NUM_CTX` | Servidor, modelo e contexto quando `LLM_PROVIDER=ollama`. |
| `LLM_TIMEOUT_SECONDS` | Tempo máximo de uma chamada ao LLM; estourar vira `failed` com `llm_unreachable`. |
| `MAX_RECORDING_SECONDS` | Teto padrão de `record-and-generate`. |
| `SAVE_DIR` | Onde as gravações e os `.docx` são salvos. |
| `API_KEY` | Chave exigida no cabeçalho `X-API-Key` (1.1) e enviada nos avisos de `callback_url` (4.7). Vazia (padrão): API aberta. Gerar com `python -c "import secrets; print(secrets.token_urlsafe(32))"`. |
| `TIMEZONE` | Fuso usado para escrever data e horário da gravação no cabeçalho (3.3). Padrão `America/Fortaleza` (Campina Grande, UTC−3). |

---

## 8. Garantias e limitações

- Jobs e seus arquivos persistem em SQLite e em disco; sobrevivem a reinício da API. Jobs que estavam `running` quando a API caiu voltam como `failed` (`internal`, "interrupted by restart").
- Jobs são executados **um por vez** na ordem de criação (fila única). Um `record_and_generate` em andamento não bloqueia a criação de outros jobs, mas eles só rodam depois dele.
- A autenticação é uma chave única compartilhada (`API_KEY`), sem usuários nem permissões por projeto. Quem tem a chave pode listar qualquer projeto e mandar o bot a qualquer reunião: ela deve ficar só no servidor do SGL. O `project_id` organiza as atas, mas não protege; o controle de quem vê o quê fica no SGL. Mesmo com chave, a API deve ficar em rede interna.
- Os nomes dos participantes vêm do nome de exibição no Teams. Fala de duas pessoas no mesmo instante pode ser atribuída à pessoa errada; identificação por voz é a Parte 2 do projeto.
- O LLM é instruído a não inventar conteúdo, mas pode errar. A ata deve ser revisada por uma pessoa antes de ser distribuída; o campo "Ata gerada automaticamente pelo GravAI" no rodapé existe para isso.
