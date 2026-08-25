"""Speech media providers behind stable contracts.

Single entry point for local speech models per MODEL_CARD.md: faster-whisper
for STT and Piper for TTS at deployment. Until GPU/media infrastructure lands,
deterministic mock providers keep the interview loop provable in CI without
any model weights or network access (same precedent as the LLM backends).

Every result carries its provider id and model id so transcripts and audio
stored by the API remain fully attributable (constraint 8.1 provenance rule).
"""

import base64
import binascii
import hashlib
import io
import math
import struct
import wave
from abc import ABC, abstractmethod

from pydantic import BaseModel, Field

MOCK_TRANSCRIBER_MODEL = "aiva-mock-deterministic-stt"
MOCK_SPEAKER_MODEL = "aiva-mock-deterministic-tts"
FASTER_WHISPER_MODEL_DEFAULT = "faster-whisper-large-v3"
PIPER_MODEL_DEFAULT = "piper-onnx-en_US-lessac-medium"

MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_SYNTH_CHARS = 4000

_MOCK_WORDS = (
    "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima "
    "mike november oscar papa quebec romeo sierra tango uniform victor whiskey "
    "xray yankee zulu".split()
)


class Transcription(BaseModel):
    text: str = Field(min_length=0)
    language: str
    confidence: float = Field(ge=0.0, le=1.0)
    duration_seconds: float = Field(ge=0.0)
    audio_sha256: str = Field(min_length=64, max_length=64)
    provider: str
    model_id: str


class Synthesis(BaseModel):
    audio_b64: str
    format: str = "wav"
    sample_rate: int = Field(gt=0)
    duration_seconds: float = Field(gt=0.0)
    text_sha256: str = Field(min_length=64, max_length=64)
    provider: str
    model_id: str


class MediaError(ValueError):
    """Raised for undecodable or out-of-policy media payloads."""


def decode_audio(audio_b64: str) -> bytes:
    try:
        raw = base64.b64decode(audio_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise MediaError("audio_b64 is not valid base64") from exc
    if not raw:
        raise MediaError("audio_b64 decodes to zero bytes")
    if len(raw) > MAX_AUDIO_BYTES:
        raise MediaError(f"audio exceeds {MAX_AUDIO_BYTES} byte cap")
    return raw


class TranscriptionProvider(ABC):
    @property
    @abstractmethod
    def model_id(self) -> str: ...

    @abstractmethod
    async def transcribe(self, audio: bytes, language: str) -> Transcription: ...


class SpeechProvider(ABC):
    @property
    @abstractmethod
    def model_id(self) -> str: ...

    @abstractmethod
    async def synthesize(self, text: str) -> Synthesis: ...


def _wav_duration_seconds(audio: bytes) -> float:
    """Best-effort duration read from a RIFF/WAVE header; size-based fallback."""
    try:
        with wave.open(io.BytesIO(audio), "rb") as handle:
            frames: int = handle.getnframes()
            rate: int = handle.getframerate()
            if rate > 0:
                return round(frames / rate, 3)
    except wave.Error:
        pass
    return round(len(audio) / 32000.0, 3)


class MockTranscriber(TranscriptionProvider):
    """Deterministic stand-in for faster-whisper.

    The transcript is a seeded token stream derived only from the audio bytes,
    so repeated submissions of the same recording produce byte-identical
    output while making clear the content is synthetic, not recognized speech.
    Duration is read from a real WAV header when present.
    """

    @property
    def model_id(self) -> str:
        return MOCK_TRANSCRIBER_MODEL

    async def transcribe(self, audio: bytes, language: str) -> Transcription:
        digest = hashlib.sha256(audio).digest()
        word_count = 4 + (digest[0] % 12)
        words = [
            _MOCK_WORDS[digest[(index * 2 + 1) % len(digest)] % len(_MOCK_WORDS)]
            for index in range(word_count)
        ]
        confidence = round(0.70 + digest[2] / 850, 3)
        return Transcription(
            text=" ".join(words),
            language=language,
            confidence=confidence,
            duration_seconds=_wav_duration_seconds(audio),
            audio_sha256=hashlib.sha256(audio).hexdigest(),
            provider="mock",
            model_id=self.model_id,
        )


class FasterWhisperTranscriber(TranscriptionProvider):
    """Real STT path; requires the faster-whisper package and weights on the box."""

    def __init__(self, model_size: str) -> None:
        self.model_size = model_size
        try:
            import faster_whisper  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "faster-whisper is not installed; pull model weights at deployment "
                "per docs/MODEL_CARD.md before selecting this backend"
            ) from exc

    @property
    def model_id(self) -> str:
        return self.model_size

    async def transcribe(self, audio: bytes, language: str) -> Transcription:
        del audio, language
        raise RuntimeError("faster-whisper inference lands with GPU deployment (M8 deferral)")


class MockSpeaker(SpeechProvider):
    """Deterministic PCM16 WAV synthesizer standing in for Piper.

    Emits a valid 16 kHz mono waveform whose length tracks the requested text
    (~150 wpm narration pacing) with a quiet hash-seeded tone, so downstream
    consumers exercise real audio plumbing with byte-reproducible output.
    """

    SAMPLE_RATE = 16000
    WORDS_PER_MINUTE = 150

    @property
    def model_id(self) -> str:
        return MOCK_SPEAKER_MODEL

    async def synthesize(self, text: str) -> Synthesis:
        words = len(text.split())
        seconds = max(1.0, round(words / (self.WORDS_PER_MINUTE / 60.0), 3))
        total_frames = int(seconds * self.SAMPLE_RATE)
        seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:4], "big")
        frequency = 180 + (seed % 120)

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(self.SAMPLE_RATE)
            fade_frames = min(total_frames // 10, 800)
            for frame in range(total_frames):
                envelope = 1.0
                if frame < fade_frames and fade_frames > 0:
                    envelope = frame / fade_frames
                elif frame > total_frames - fade_frames and fade_frames > 0:
                    envelope = (total_frames - frame) / fade_frames
                amplitude = int(1200 * envelope)
                sample = int(
                    amplitude * math.sin(2 * math.pi * frequency * frame / self.SAMPLE_RATE)
                )
                handle.writeframes(struct.pack("<h", sample))
        pcm = buffer.getvalue()
        return Synthesis(
            audio_b64=base64.b64encode(pcm).decode("ascii"),
            format="wav",
            sample_rate=self.SAMPLE_RATE,
            duration_seconds=seconds,
            text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            provider="mock",
            model_id=self.model_id,
        )


class PiperSpeaker(SpeechProvider):
    """Real TTS path; requires the piper package and ONNX voices on the box."""

    def __init__(self, voice: str) -> None:
        self.voice = voice
        try:
            import piper  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "piper is not installed; pull ONNX voices at deployment per "
                "docs/MODEL_CARD.md before selecting this backend"
            ) from exc

    @property
    def model_id(self) -> str:
        return self.voice

    async def synthesize(self, text: str) -> Synthesis:
        del text
        raise RuntimeError("piper inference lands with deployment of ONNX voices (M8 deferral)")


def build_transcriber(backend: str, model_size: str) -> TranscriptionProvider:
    if backend == "mock":
        return MockTranscriber()
    if backend == "faster-whisper":
        return FasterWhisperTranscriber(model_size)
    raise ValueError(f"Unknown STT backend: {backend}")


def build_speaker(backend: str, voice: str) -> SpeechProvider:
    if backend == "mock":
        return MockSpeaker()
    if backend == "piper":
        return PiperSpeaker(voice)
    raise ValueError(f"Unknown TTS backend: {backend}")


__all__ = [
    "MAX_AUDIO_BYTES",
    "MAX_SYNTH_CHARS",
    "MediaError",
    "MockSpeaker",
    "MockTranscriber",
    "SpeechProvider",
    "Synthesis",
    "Transcription",
    "TranscriptionProvider",
    "build_speaker",
    "build_transcriber",
    "decode_audio",
]
