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
docker compose -f docker-compose.yaml up -d
```

2.b. Or deploy the GravAI docker-compose with whisper built-in: (Optional)
```bash
docker compose -f docker-compose-whisper.yaml up -d
```

3. Connect to the instance [http://localhost:8000](http://localhost:8000)

### Local development (uv)

The project uses [uv](https://docs.astral.sh/uv/) to manage the virtual environment and dependencies. Every command runs through `uv run`, so there is no need to activate anything.

```bash
# Install uv (once)
winget install astral-sh.uv          # Windows
curl -LsSf https://astral.sh/uv/install.sh | sh   # Linux / macOS

# Create .venv and install the dependencies from uv.lock
uv sync

# Playwright browsers (only needed to record meetings)
uv run playwright install

# Run the API with auto reload
uv run fastapi dev api/app.py

# Run the tests
uv run pytest

# Add or remove a dependency (updates pyproject.toml and uv.lock)
uv add <package>
uv remove <package>
```

### Minutes (atas)

The `minutes/` module turns a recording folder into a meeting-minutes document. Each step has a small CLI so it can be exercised without the others:

```bash
# Merge the per-participant whisper output of a recording into one transcript
uv run python -m minutes.transcript_normalizer tmp/<session>_tracks
uv run python -m minutes.transcript_normalizer tmp/<session>_tracks -o transcript.json

# Show the prompts built for a transcript
uv run python -m minutes.prompt_builder minutes/tests/fixtures/reuniao_dell.json

# Whole pipeline: transcript -> LLM -> .docx (LLM configured in .env)
uv run python -m minutes.generate minutes/tests/fixtures/reuniao_dell.json -o ata.docx --json

# Render already-filled minutes as .docx (no LLM involved)
uv run python -m minutes.docx_writer minutes/tests/fixtures/ata_dell_preenchida.json -o ata.docx
```

The LLM is configured in `.env` (`LLM_PROVIDER`, `OLLAMA_HOST`, `OLLAMA_MODEL`); the default is a local Ollama server. `LLM_PROVIDER=fake` fills every section with placeholder text so the pipeline can be exercised without any LLM. Templates live in `minutes/templates/`, see the README there. The HTTP contract for generating minutes is in `docs/API_MINUTES.md`. Generation runs as background jobs (`jobs/`: SQLite store, one worker thread, one executor per job kind) so HTTP clients only poll:

```bash
# API with the fake LLM (no Ollama needed)
LLM_PROVIDER=fake uv run fastapi dev api/app.py

curl http://localhost:8000/minutes/templates
curl -X POST http://localhost:8000/minutes/from-transcript -H "Content-Type: application/json" -d @minutes/tests/fixtures/reuniao_dell.json
curl http://localhost:8000/minutes/jobs/<id>            # poll until status is done
curl -OJ http://localhost:8000/minutes/jobs/<id>/download
```

A demonstration page that drives the same endpoints is served at [http://localhost:8000/demo](http://localhost:8000/demo): pick a template, fill the header, paste a transcript (or point to a recording, or give a Teams link), follow the job and download the `.docx`.

The project is early-stage and evolving. Expect breaking changes as we harden reliability and multi-platform support.
