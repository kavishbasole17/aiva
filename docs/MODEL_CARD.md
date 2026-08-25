# MODEL CARD INDEX

Every model used by AIVA gets a card here before it ships (constraint §1.6):
purpose, licence (with internal-commercial-use clearance note), version +
quantisation pin, hardware envelope, eval results on the golden set, known
limitations, and drift-monitor linkage.

No models are wired at Milestone 0. The first cards land with `ai-gateway` at
Milestone 3.

## Planned capabilities → cards

| Capability | Candidate model | Card |
|---|---|---|
| LLM reasoning/scoring | Qwen2.5-14B-Instruct AWQ (fallback Llama-3.1-8B-Instruct) | pending M3 |
| Embeddings | bge-m3 (1024-dim) | pending M3 |
| STT | faster-whisper large-v3 / distil-large-v3 | interface shipped M8 (mock-verified); weights pending GPU deployment |
| TTS | Piper ONNX voices | interface shipped M8 (mock-verified); voices pending deployment |
| Resume NER | spaCy pipeline | pending M4 |
| OCR fallback | PaddleOCR / Tesseract | pending M4 |
| Identity match | InsightFace ArcFace (+ consent gate) | deferred from M8 to M11 integrity work |
| Proctoring signals | MediaPipe Face Mesh | deferred from M8 to M11 integrity work |
| Reranker | bge-reranker-v2-m3 | pending M10 |

Licence review rule: Apache-2.0/MIT preferred; anything with a bespoke community
licence is flagged for human legal review before integration, never assumed.
