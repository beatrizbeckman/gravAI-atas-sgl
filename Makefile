MODELO ?= large-v3-turbo

exec-playright:
	uv sync
	uv run playwright install-deps
	uv run playwright install

run-api:
	uv run fastapi dev gravai/api/app.py

download-model:
	@cd ../whisper.cpp && sh ./models/download-ggml-model.sh ${MODELO}

build-whisper:
	@cd ../whisper.cpp && cmake -B build && cmake --build build -j --config Release

exec-whisper:
	@cd ../whisper.cpp && ./build/bin/whisper-server -m models/ggml-$(MODELO).bin --host 0.0.0.0 --language pt
