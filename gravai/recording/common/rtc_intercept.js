(() => {
  const WS_URL = "{{WS_URL}}";
  const WORKLET_CODE = {{WORKLET_CODE}};
  const WORKLET_URL = URL.createObjectURL(
    new Blob([WORKLET_CODE], { type: "application/javascript" })
  );

  const handlers = new Map();

  function openSocket(trackId, sampleRate, channels) {
    const url = new URL(WS_URL);
    url.searchParams.set("track", trackId);
    url.searchParams.set("sr", String(sampleRate));
    url.searchParams.set("ch", String(channels));
    const ws = new WebSocket(url.toString());
    ws.binaryType = "arraybuffer";
    ws.onopen = () => {
      ws.send(JSON.stringify({ type: "start", trackId, sampleRate, channels }));
    };
    return ws;
  }

  async function attachTrack(track) {
    if (track.kind !== "audio") return;
    if (handlers.has(track.id)) return;

    console.log("[rtc-intercept] attaching track", track.id);

    const ctx = new AudioContext({ sampleRate: 48000 });
    await ctx.audioWorklet.addModule(WORKLET_URL);
    if (ctx.state !== "running") {
      await ctx.resume();
    }

    const settings = track.getSettings ? track.getSettings() : {};
    const trackSampleRate = settings.sampleRate || null;
    const trackChannels = settings.channelCount || 1;
    console.log("[rtc-intercept] AudioContext sampleRate", ctx.sampleRate, "track sampleRate", trackSampleRate);

    const source = new MediaStreamAudioSourceNode(ctx, { mediaStream: new MediaStream([track]) });
    const node = new AudioWorkletNode(ctx, "pcm-collector");
    const gain = new GainNode(ctx, { gain: 0 });

    source.connect(node);
    node.connect(gain).connect(ctx.destination);

    const ws = openSocket(track.id, ctx.sampleRate, trackChannels);
    const queue = [];
    let wsReady = false;

    ws.addEventListener("open", () => {
      wsReady = true;
      console.log("[rtc-intercept] ws open", track.id);
      while (queue.length) {
        ws.send(queue.shift());
      }
    });
    ws.addEventListener("error", (event) => {
      console.log("[rtc-intercept] ws error", event);
    });

    node.port.onmessage = (event) => {
      const data = event.data;
      if (!data) return;
      let payload;
      if (data instanceof ArrayBuffer) {
        payload = data;
      } else if (data.buffer) {
        payload = data.buffer;
      } else {
        return;
      }
      if (!wsReady) {
        queue.push(payload);
      } else {
        ws.send(payload);
      }
    };

    track.onended = () => {
      try {
        ws.send(JSON.stringify({ type: "stop", trackId: track.id }));
      } catch (e) {
        
      }
      try {
        ws.close();
      } catch (e) {

      }
      try {
        ctx.close();
      } catch (e) {

      }
      handlers.delete(track.id);
    };

    handlers.set(track.id, { ctx, ws, node });
  }

  const OriginalRTCPeerConnection = window.RTCPeerConnection;
  window.RTCPeerConnection = new Proxy(OriginalRTCPeerConnection, {
    construct(target, args) {
      const pc = new target(...args);
      console.log("[rtc-intercept] RTCPeerConnection created");
      pc.addEventListener("track", (event) => {
        if (event && event.track) {
          attachTrack(event.track);
        }
      });
      return pc;
    },
  });
})();
