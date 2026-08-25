import { Badge, Button, Card, Field } from "@aiva/ui";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  browserLabel,
  classifyConnection,
  peakAudioLevel,
} from "../audio";
import { downloadThroughputKbps, healthLatencyMs } from "../api";
import type { DeviceCheck, PreCheckReport } from "../api";

interface Props {
  suiteVersion: string;
  onPassed: (report: PreCheckReport) => Promise<void>;
}

type CameraState = "idle" | "live" | "failed";
type MicState = "idle" | "listening" | "silent" | "ok" | "failed";
type SpeakerState = "untested" | "played" | "heard";

const MIC_OK_THRESHOLD = 0.06;

export default function PreCheckGate({ suiteVersion, onPassed }: Props) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const [camera, setCamera] = useState<CameraState>("idle");
  const [mic, setMic] = useState<MicState>("idle");
  const [speaker, setSpeaker] = useState<SpeakerState>("untested");
  const [level, setLevel] = useState(0);
  const [latency, setLatency] = useState<number | null>(null);
  const [bandwidth, setBandwidth] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const stopStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
  }, []);

  useEffect(() => stopStream, [stopStream]);

  async function startDevices(): Promise<void> {
    setError(null);
    stopStream();
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: true,
        audio: { echoCancellation: true },
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => undefined);
      }
      setCamera("live");
      setMic("listening");
      const peak = await peakAudioLevel(stream, 3500);
      setLevel(peak);
      if (peak >= MIC_OK_THRESHOLD) {
        setMic("ok");
      } else {
        setMic("silent");
      }
    } catch (exception) {
      setCamera("failed");
      setMic("failed");
      setError(
        exception instanceof Error ? exception.message : "Camera/microphone permission denied",
      );
    }
  }

  function playTone(): void {
    try {
      const context = new AudioContext();
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      oscillator.frequency.value = 440;
      gain.gain.setValueAtTime(0.15, context.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, context.currentTime + 1.2);
      oscillator.connect(gain).connect(context.destination);
      oscillator.start();
      oscillator.stop(context.currentTime + 1.2);
      oscillator.onended = () => void context.close();
      setSpeaker("played");
    } catch {
      setError("Browser blocked audio playback; press play again after interacting.");
    }
  }

  async function measureConnection(): Promise<void> {
    setError(null);
    try {
      const rtt = await healthLatencyMs();
      setLatency(rtt);
      const kbps = await downloadThroughputKbps();
      setBandwidth(kbps);
    } catch {
      setError("Could not reach the interview service for the connection sample.");
    }
  }

  async function submit(): Promise<void> {
    const connection = latency === null ? "unknown" : classifyConnection(latency);
    const devices: DeviceCheck[] = [
      {
        kind: "camera",
        status: camera === "live" ? "ok" : camera === "failed" ? "failed" : "missing",
        label: camera === "live" ? "Live preview running" : "No camera feed",
      },
      {
        kind: "microphone",
        status:
          mic === "ok"
            ? "ok"
            : mic === "silent" || mic === "listening"
              ? "degraded"
              : "failed",
        label:
          mic === "ok"
            ? `Voice detected (peak ${Math.round(level * 100)}%)`
            : mic === "silent"
              ? "Feed open but no voice detected"
              : "No microphone access",
      },
      {
        kind: "speaker",
        status: speaker === "heard" ? "ok" : speaker === "played" ? "degraded" : "missing",
        label: speaker === "heard" ? "Test tone confirmed" : "Test tone not confirmed",
      },
    ];
    const report: PreCheckReport = {
      suite_version: suiteVersion,
      devices,
      connection,
      bandwidth_kbps: bandwidth ?? 0,
      browser: browserLabel(),
    };
    setSubmitting(true);
    try {
      await onPassed(report);
    } finally {
      setSubmitting(false);
    }
  }

  const readyToSubmit =
    camera === "live" && speaker === "heard" && latency !== null && bandwidth !== null;

  return (
    <Card>
      <p className="text-sm uppercase tracking-widest text-[var(--haze)]">Step 2 of 3</p>
      <h1 className="display mt-2 text-2xl font-bold">Equipment check</h1>
      <p className="mt-2 leading-relaxed">
        We verify your camera, microphone, speaker and connection before the interview starts.
        Everything runs in your browser — nothing is recorded yet.
      </p>

      <div className="mt-6 grid gap-6 sm:grid-cols-2">
        <div>
          <video
            ref={videoRef}
            muted
            playsInline
            className="aspect-video w-full rounded-lg border border-[var(--steel)] bg-black object-cover"
          />
          <div className="mt-3 flex items-center gap-3">
            <Badge tone={camera === "live" ? "positive" : camera === "failed" ? "negative" : "neutral"}>
              Camera {camera}
            </Badge>
            <Badge
              tone={
                mic === "ok"
                  ? "positive"
                  : mic === "silent" || mic === "listening"
                    ? "warning"
                    : mic === "failed"
                      ? "negative"
                      : "neutral"
              }
            >
              Microphone {mic === "idle" ? "" : mic}
            </Badge>
          </div>
          {mic === "listening" && (
            <div className="mt-3 h-2 w-full overflow-hidden rounded bg-[var(--abyss)]">
              <div className="h-full w-1/3 animate-pulse rounded bg-[var(--signal)]" />
            </div>
          )}
          {mic === "silent" && (
            <p className="mt-2 text-sm text-[var(--haze)]">
              Feed is live but we never heard your voice (peak {Math.round(level * 100)}%).
              Speak towards the microphone and re-run.
            </p>
          )}
        </div>

        <div className="flex flex-col gap-4">
          <Field label="1. Camera & microphone" htmlFor="precheck-devices">
            <Button variant="action" onClick={() => void startDevices()} id="precheck-devices">
              {camera === "idle" ? "Start camera & mic test" : "Re-run device test"}
            </Button>
          </Field>

          <Field label="2. Speaker" htmlFor="precheck-speaker">
            <Button variant="action" onClick={playTone} disabled={speaker === "played"} id="precheck-speaker">
              Play test tone
            </Button>
            {speaker === "played" && (
              <Button variant="ghost" onClick={() => setSpeaker("heard")}>
                I heard the tone
              </Button>
            )}
          </Field>

          <Field label="3. Connection" htmlFor="precheck-connection">
            <Button
              variant="action"
              onClick={() => void measureConnection()}
              id="precheck-connection"
            >
              Run connection sample
            </Button>
            {latency !== null && (
              <p className="mt-1 text-sm text-[var(--haze)]">
                Round-trip {latency} ms · ~{bandwidth ?? "?"} kbps downstream
              </p>
            )}
          </Field>
        </div>
      </div>

      {error && (
        <p role="alert" className="mt-4 text-sm text-[var(--danger, #e5484d)]">
          {error}
        </p>
      )}

      <div className="mt-6 flex justify-end">
        <Button
          onClick={() => void submit()}
          disabled={!readyToSubmit || submitting}
          title={
            readyToSubmit
              ? "Submit equipment report"
              : "Complete all three checks to continue"
          }
        >
          Submit check
        </Button>
      </div>
    </Card>
  );
}
