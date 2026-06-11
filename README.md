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

The project is early-stage and evolving. Expect breaking changes as we harden reliability and multi-platform support.
