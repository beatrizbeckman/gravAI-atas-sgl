## GravAI

GravAI is a privacy-first system designed to join online meetings, capture per-participant audio, and prepare the data for transcription, diarization, and downstream LLM workflows (meeting reports, summaries, action items, and other custom use cases), all done locally. The focus is multi-platform meeting recording, supporting major providers such as Microsoft Teams and Google Meet, with an API-first flow and a pipeline that is easy to connect to custom workflows.

### Intended Features

- Record meetings across multiple platforms.
- Capture per-track audio and session metadata.
- Transcribe and diarize audio.
- Enable easy coupling with LLM workflows such as meeting report generation and summarization.

### What is working today

- FastAPI endpoints to trigger recording and transcribe.
- Teams meeting recording (WIP) with per-participant audio output.
- WebSocket audio server writing per-track WAV files and session metadata sidecar.
- Transcription via Whisper.

### Roadmap

- Support for multiple concurrent recordings (shared WS server and routing improvements).
- Improve the UI element matching for better per-participant audio slicing.
- Support more providers (Google Meet, Zoom, etc).
- Add diarization support as an optional step.
- Integrate LLM workflows (summaries, minutes, action items, knowledge base sync).
- Better observability, retries, and error reporting for long sessions.

### Setup

1. Copy the env file and define its variables accordingly:
```bash
cp .env.example .env
```

2. Clone and set Whisper repository:
```bash
git clone https://github.com/ggml-org/whisper.cpp.git
cd whisper.cpp
# Runs the official script that downloads a Whisper model
sh ./models/download-ggml-model.sh large-v3-turbo
# Configures the build system
cmake -B build
# Compiles the code
cmake --build build -j --config Release
# Starts the whisper server
./whisper.cpp/build/bin/whisper-server -m whisper.cpp/models/ggml-large-v3-turbo.bin --host 0.0.0.0 --language pt
```

2.a. Start your external whisper server for transcription and specify the WHISPER_HOST and WHISPER_PORT accordingly on .env file and the GravAI docker-compose without: (Optional)
```bash
docker compose -f docker/docker-compose.yaml up -d
```

2.b. Or deploy the GravAI docker-compose with whisper built-in: (Optional)
```bash
docker compose -f docker/docker-compose-whisper.yaml up -d
```

3. Connect to the instance [http://localhost:8000](http://localhost:8000)

### Local development (virtual environment)

The project uses [uv](https://docs.astral.sh/uv/) to manage the virtual environment and dependencies. `uv sync` creates `.venv/` from `uv.lock` with everything, including the dev tools (pytest, ruff). Every command then runs through `uv run`, so there is no need to activate anything.

```bash
# Install uv (once)
winget install astral-sh.uv          # Windows
curl -LsSf https://astral.sh/uv/install.sh | sh   # Linux / macOS

# Create .venv and install the dependencies from uv.lock
uv sync

# Playwright browsers (only needed to record meetings)
uv run playwright install

# Run the API with auto reload
uv run fastapi dev gravai/api/app.py

# Run the tests, the linter and the formatter
uv run pytest
uv run ruff check .
uv run ruff format .

# Add or remove a dependency (updates pyproject.toml and uv.lock)
uv add <package>
uv remove <package>
```

Without uv, a plain virtual environment works too; `requirements.txt` is exported from `uv.lock` (regenerate it with `uv export --no-hashes -o requirements.txt` after changing dependencies):

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
source .venv/bin/activate          # Linux / macOS
pip install -r requirements.txt
pytest
```

### Minutes (atas)

The `gravai/minutes/` module turns a recording folder into a meeting-minutes document. Each step has a small CLI so it can be exercised without the others. The example transcripts are the real meetings of the dataset in `datasets/reunioes/` (see `datasets/README.md`):

```bash
# Merge the per-participant whisper output of a recording into one transcript
uv run python -m gravai.minutes.transcript_normalizer tmp/<session>_tracks
uv run python -m gravai.minutes.transcript_normalizer tmp/<session>_tracks -o transcript.json

# Show the prompts built for a transcript
uv run python -m gravai.minutes.prompt_builder datasets/reunioes/ES2004a/transcricao.json

# Whole pipeline: transcript -> LLM -> .docx (LLM configured in .env)
uv run python -m gravai.minutes.generate datasets/reunioes/ES2004a/transcricao.json -o ata.docx --json

# Render minutes an LLM already produced (e.g. from an experiment run) as .docx, no LLM involved
uv run python -m gravai.minutes.docx_writer datasets/reunioes/ES2004a/transcricao.json experiments/results/<run>/<pair>/minutes.json -o ata.docx

# Compare models over the whole dataset (prompts, raw replies, docx, time, tokens, cost per pair)
uv run python experiments/run_experiments.py --max-chars 12000
```

The LLM is configured in `.env` (`LLM_PROVIDER` and the `LLM_*` / `OLLAMA_*` variables). `openai_compatible` calls an online API in the OpenAI format (Groq, DeepInfra, OpenAI...), `ollama` a local server, and `fake` fills every section with placeholder text so the pipeline can be exercised without any LLM. Templates live in `gravai/minutes/templates/`, see the README there. The HTTP contract for generating minutes is in `docs/API_MINUTES.md`. Generation runs as background jobs (`gravai/jobs/`: SQLite store, one worker thread, one executor per job kind) so HTTP clients only poll:

```bash
# API with the fake LLM (no LLM needed)
LLM_PROVIDER=fake uv run fastapi dev gravai/api/app.py

curl http://localhost:8000/minutes/templates
curl -X POST http://localhost:8000/minutes/from-transcript -H "Content-Type: application/json" -d @datasets/reunioes/ES2004a/transcricao.json
curl http://localhost:8000/minutes/jobs/<id>            # poll until status is done
curl -OJ http://localhost:8000/minutes/jobs/<id>/download
```

A demonstration page that drives the same endpoints is served at [http://localhost:8000/demo](http://localhost:8000/demo): pick a template, fill the header, paste a transcript (or point to a recording, or give a Teams link), follow the job and download the `.docx`.

[http://localhost:8000/demo/sgl](http://localhost:8000/demo/sgl) is only the content of the SGL "Reuniões" tab (the SGL's sidebar, project card and other tabs are not repeated), in the SGL's daisyUI `business` theme (loaded from a CDN, so it needs internet), driving the real API: record a meeting and stop it, the project's minutes (view and Word), and the custom model editor with "describe in text → sections" and "save as the project's model". The project is fixed (in the SGL the tab sits inside one project's page); meeting titles and project models live in the browser's localStorage, standing in for what the SGL already has. To generate minutes without Teams, use `/demo` with a dataset meeting.

### Testing on a server, the way the SGL calls the API

The SGL (the lab's project system) calls the same HTTP routes from its server, so they can be exercised with `curl` before the SGL side exists. Contract: `docs/API_MINUTES.md` (section 3.6 is the meeting flow).

**1. Configure and start** (Docker with the bundled whisper). Lines that matter in `.env`:

```dotenv
WHISPER_HOST=whisper
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_API_KEY=<groq key>
LLM_MODEL=openai/gpt-oss-120b
API_KEY=<any secret; clients send it in X-API-Key>
TIMEZONE=America/Fortaleza
```

```bash
sudo docker compose --env-file .env -f docker/docker-compose-whisper.yaml up -d --build
sudo docker logs --tail 15 gravai-app          # "Application startup complete"
sudo docker logs -f --tail 20 gravai-app       # keep open in a second terminal
```

`.env` is read only at startup: after changing it, `restart app`; after changing code, `up -d --build app`.

**2. Shell helpers** (paste again in every new terminal):

```bash
API=http://localhost:8000
KEY=<the API_KEY above>
id_do_job() { python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('id') or d)"; }
situacao() { curl -sS -H "X-API-Key: $KEY" "$API/minutes/jobs/$1" | python3 -c "import json,sys; j=json.load(sys.stdin); print(j['status'], j['stage'] or '', (j['error'] or {}).get('code',''), (j['error'] or {}).get('message','')[:200])"; }
acompanhar() { while :; do s=$(situacao "$1"); echo "$(date +%T) $s"; case "$s" in done*|failed*) break;; esac; sleep 15; done; }
```

**3. Access key**: expect `401` without the key and `200` with it.

```bash
curl -sS -o /dev/null -w "%{http_code}\n" $API/minutes/templates
curl -sS -o /dev/null -w "%{http_code}\n" -H "X-API-Key: $KEY" $API/minutes/templates
```

**3b. Custom minutes from a description** (the SGL "customize the minutes" screen): the LLM turns a description into sections; send the returned `custom` with `"template":"custom"` in any request below.

```bash
curl -sS -X POST $API/minutes/templates/draft -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"description":"Quero o objetivo do projeto, as decisões e as tarefas com responsável e prazo."}' | python3 -m json.tool
```

**4. Minutes from a ready transcript** (a dataset meeting, tagged with a project):

```bash
python3 -c "import json; d=json.load(open('datasets/reunioes/ES2004a/transcricao.json')); d['project_id']='sgl-teste'; json.dump(d, open('/tmp/es2004a.json','w'))"
JOB=$(curl -sS -X POST $API/minutes/from-transcript -H "X-API-Key: $KEY" -H "Content-Type: application/json" --data-binary @/tmp/es2004a.json | id_do_job); echo $JOB
acompanhar $JOB
curl -sS -H "X-API-Key: $KEY" $API/minutes/jobs/$JOB/result | python3 -m json.tool | less
```

**5. Minutes from a recording that was already transcribed** (`data` is required here because nothing is recorded):

```bash
JOB=$(curl -sS -X POST $API/minutes/from-recording -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"project_id":"sgl-teste","template":"dell","header":{"projeto":"Teste","data":"22/10/2026"},"tracks_dir":"/app/tmp/<session>_tracks"}' | id_do_job); echo $JOB
acompanhar $JOB
```

**6. Live meeting: the bot joins, records, is stopped and writes the minutes.** This is the SGL meeting tab. The header carries only the project; date and time come from the recording.

```bash
LINK='https://teams.live.com/meet/...'           # paste only the link, between single quotes
JOB=$(curl -sS -X POST $API/minutes/record-and-generate -H "X-API-Key: $KEY" -H "Content-Type: application/json" -d "{\"project_id\":\"sgl-teste\",\"template\":\"dell\",\"header\":{\"projeto\":\"Teste\"},\"meeting_url\":\"$LINK\"}" | id_do_job); echo $JOB
situacao $JOB                                     # admit "GravAI Bot" in Teams (~40 s); then "running recording"
# ... talk: a topic, a decision, a task with owner and deadline ...
curl -sS -X POST -H "X-API-Key: $KEY" $API/minutes/jobs/$JOB/stop -w "\nHTTP %{http_code}\n"   # 202: the bot leaves
acompanhar $JOB                                   # transcribing -> generating -> done
curl -sS -H "X-API-Key: $KEY" $API/minutes/jobs/$JOB | python3 -m json.tool | grep -A4 '"header"'   # date and time filled
```

Ending the meeting for everyone in Teams also makes the bot leave. If everyone only leaves the call, it stays until `MAX_RECORDING_SECONDS`.

**7. Minutes of a project** (what the SGL tab lists):

```bash
curl -sS -H "X-API-Key: $KEY" "$API/minutes/jobs?project_id=sgl-teste" | python3 -c "import json,sys; [print(j['id'][:8], j['kind'], j['status'], j['header'].get('data','')) for j in json.load(sys.stdin)['jobs']]"
```

**8. Word files**: download on the server, then copy them on your own machine.

```bash
for id in $(curl -sS -H "X-API-Key: $KEY" "$API/minutes/jobs?project_id=sgl-teste&status=done" | python3 -c "import json,sys; print(' '.join(j['id'] for j in json.load(sys.stdin)['jobs']))"); do curl -sS -H "X-API-Key: $KEY" "$API/minutes/jobs/$id/download" -o "ata-${id:0:8}.docx"; done; ls -l ata-*.docx
# on your machine (scp runs where the files go; -P is the SSH port):
scp -P <port> "<user>@<server>:~/gravAI-atas-sgl/ata-*.docx" .
```

**When something fails.** `situacao` shows the error code. `llm_unreachable` with `(401)` means a wrong `LLM_API_KEY` (fix `.env`, then `restart app`). A minutes made only of "Legenda ..." lines means whisper got audio it could not understand; measure the tracks with `sudo docker exec gravai-app ffmpeg -hide_banner -i /app/tmp/<session>_tracks/<track>.wav -af volumedetect -f null - 2>&1 | grep max_volume` (around -91 dB is silence).

The project is early-stage and evolving. Expect breaking changes as we harden reliability and multi-platform support.
