class PCMCollector extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0) {
      return true;
    }
    const channels = input.length;
    const frames = input[0].length;
    const out = new Float32Array(frames * channels);
    for (let i = 0; i < frames; i += 1) {
      for (let c = 0; c < channels; c += 1) {
        out[i * channels + c] = input[c][i] || 0;
      }
    }
    this.port.postMessage(out, [out.buffer]);
    return true;
  }
}

registerProcessor("pcm-collector", PCMCollector);
