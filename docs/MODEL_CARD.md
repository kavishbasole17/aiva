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
| LLM reasoning/scoring | Qwen2.5-14B-Instruct AWQ (fallback Llama-3.1-8B-Instruct) | interface + prompt registry shipped M3 (mock-verified, `services/ai-gateway`); weights pending GPU deployment |
| Embeddings | all-MiniLM-L6-v2 (384-dim) — revised down from the original bge-m3/1024-dim plan; a smaller model was judged sufficient for FAQ-document retrieval scale | interface shipped M10 (`MockEmbedder`/`SentenceTransformerEmbedder`, mock-verified); weights pending GPU deployment |
| STT | faster-whisper large-v3 / distil-large-v3 | interface shipped M8 (mock-verified); weights pending GPU deployment |
| TTS | Piper ONNX voices | interface shipped M8 (mock-verified); voices pending deployment |
| Resume NER | spaCy pipeline | pending M4 — M4 shipped without it: deterministic regex/lexicon extraction (email/phone/LinkedIn/skills/years/name) proved sufficient and needed no model; spaCy NER remains a possible future precision improvement, not a blocking gap |
| OCR fallback | PaddleOCR / Tesseract | pending — no scanned/image-only resumes encountered yet; add when the need is demonstrated, not speculatively |
| Identity match | InsightFace ArcFace (+ consent gate) | still deferred to GPU deployment — M11's integrity-signals work deliberately shipped a zero-ML alternative instead (browser tab-focus/visibility events, ADR-023) rather than a face-analysis mock with no real input pipeline to stand in for |
| Proctoring signals | MediaPipe Face Mesh | still deferred to GPU deployment, same reasoning as identity match above (ADR-023) |
| Reranker | bge-reranker-v2-m3 | not built — M10 shipped direct pgvector cosine-similarity top-K retrieval for the FAQ RAG feature, which needed no separate reranking stage at this document-set scale; revisit only if retrieval quality demands it |

Licence review rule: Apache-2.0/MIT preferred; anything with a bespoke community
licence is flagged for human legal review before integration, never assumed.
