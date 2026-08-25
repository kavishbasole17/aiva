import base64
import hashlib
import io
import struct
import wave

import httpx

from app.media import MediaError, MockSpeaker, MockTranscriber, decode_audio


def _wav_bytes(seconds: float, rate: int = 8000) -> bytes:
    frames = int(seconds * rate)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        for index in range(frames):
            handle.writeframes(struct.pack("<h", 40 * (index % 7)))
    return buffer.getvalue()


def test_decode_audio_rejects_invalid_base64() -> None:
    try:
        decode_audio("not!!valid@@")
    except MediaError:
        return
    raise AssertionError("expected MediaError")


def test_decode_audio_rejects_empty_payload() -> None:
    try:
        decode_audio(base64.b64encode(b"").decode("ascii"))
    except MediaError:
        return
    raise AssertionError("expected MediaError")


async def test_mock_transcriber_is_deterministic() -> None:
    audio = _wav_bytes(1.5)
    transcriber = MockTranscriber()
    first = await transcriber.transcribe(audio, "en")
    second = await transcriber.transcribe(audio, "en")
    assert first.model_dump() == second.model_dump()
    assert first.audio_sha256 == hashlib.sha256(audio).hexdigest()
    assert first.duration_seconds == 1.5
    assert first.text
    changed = await transcriber.transcribe(_wav_bytes(2.0), "en")
    assert changed.text != first.text or changed.duration_seconds != first.duration_seconds


async def test_mock_speaker_emits_valid_wav_deterministically() -> None:
    speaker = MockSpeaker()
    text = "Tell me about your experience with distributed systems."
    first = await speaker.synthesize(text)
    second = await speaker.synthesize(text)
    assert first.audio_b64 == second.audio_b64
    assert first.format == "wav"
    assert first.sample_rate == speaker.SAMPLE_RATE
    pcm = base64.b64decode(first.audio_b64)
    with wave.open(io.BytesIO(pcm), "rb") as handle:
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        assert handle.getframerate() == speaker.SAMPLE_RATE
        assert abs(handle.getnframes() / handle.getframerate() - first.duration_seconds) < 0.01


async def test_stt_endpoint_roundtrip(client: httpx.AsyncClient) -> None:
    audio = _wav_bytes(0.8)
    payload = {"audio_b64": base64.b64encode(audio).decode("ascii"), "language": "en"}
    first = await client.post("/v1/stt", json=payload)
    assert first.status_code == 200, first.text
    body_first = first.json()
    assert body_first["provider"] == "mock"
    assert len(body_first["audio_sha256"]) == 64
    second = await client.post("/v1/stt", json=payload)
    assert second.json() == body_first

    invalid = await client.post("/v1/stt", json={"audio_b64": "@@bad@@"})
    assert invalid.status_code == 400


async def test_tts_endpoint_roundtrip(client: httpx.AsyncClient) -> None:
    payload = {"text": "Please describe your favorite project."}
    first = await client.post("/v1/tts", json=payload)
    assert first.status_code == 200, first.text
    body_first = first.json()
    assert body_first["format"] == "wav"
    second = await client.post("/v1/tts", json=payload)
    assert second.json()["audio_b64"] == body_first["audio_b64"]

    empty = await client.post("/v1/tts", json={"text": ""})
    assert empty.status_code == 422


async def test_media_backends_listed(client: httpx.AsyncClient) -> None:
    response = await client.get("/media-backends")
    assert response.status_code == 200
    body = response.json()
    assert body["stt"]["provider"] == "MockTranscriber"
    assert body["tts"]["provider"] == "MockSpeaker"
