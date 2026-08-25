export function base64ToBlobUrl(audioB64: string, mimeType = "audio/wav"): string {
  const binary = atob(audioB64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return URL.createObjectURL(new Blob([bytes], { type: mimeType }));
}

export function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = typeof reader.result === "string" ? reader.result : "";
      const commaIndex = result.indexOf(",");
      resolve(commaIndex >= 0 ? result.slice(commaIndex + 1) : "");
    };
    reader.onerror = () => reject(reader.error ?? new Error("Could not read recording"));
    reader.readAsDataURL(blob);
  });
}

export async function peakAudioLevel(stream: MediaStream, windowMs: number): Promise<number> {
  const context = new AudioContext();
  try {
    const source = context.createMediaStreamSource(stream);
    const analyser = context.createAnalyser();
    analyser.fftSize = 512;
    source.connect(analyser);
    const buffer = new Float32Array(analyser.fftSize);
    const deadline = performance.now() + windowMs;
    let peak = 0;
    while (performance.now() < deadline) {
      analyser.getFloatTimeDomainData(buffer);
      for (const sample of buffer) {
        const magnitude = Math.abs(sample);
        if (magnitude > peak) peak = magnitude;
      }
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    return peak;
  } finally {
    void context.close();
  }
}

export function classifyConnection(latencyMs: number): "good" | "fair" | "poor" | "unknown" {
  if (latencyMs <= 0) return "unknown";
  if (latencyMs < 150) return "good";
  if (latencyMs < 400) return "fair";
  if (latencyMs < 1200) return "poor";
  return "unknown";
}

export function browserLabel(): string {
  const raw = navigator.userAgent;
  return raw.length > 64 ? raw.slice(0, 64) : raw;
}
