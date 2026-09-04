import { useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Badge, Button, Card } from "@aiva/ui";
import { createWeightProfile, runScoring, uploadResume } from "../api/client";

const DEFAULT_WEIGHTS = {
  technical: 30,
  experience: 20,
  domain: 15,
  education: 10,
  certifications: 10,
  soft_skills: 10,
  stability: 5,
};

type FileStatus = "pending" | "uploading" | "uploaded" | "scoring" | "scored" | "error";

interface FileRow {
  file: File;
  status: FileStatus;
  resumeId?: string;
  score?: number;
  verdict?: string;
  error?: string;
}

const VERDICT_TONE: Record<string, "positive" | "accent" | "warning" | "negative"> = {
  highly_recommended: "accent",
  shortlist: "positive",
  hold: "warning",
  auto_reject: "negative",
};

export function ResumeUploadPage() {
  const { id: requisitionId } = useParams();
  const [rows, setRows] = useState<FileRow[]>([]);
  const [scoringAll, setScoringAll] = useState(false);
  const [scoringError, setScoringError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  if (!requisitionId) return null;

  function addFiles(fileList: FileList | null) {
    if (!fileList) return;
    const next: FileRow[] = Array.from(fileList).map((file) => ({ file, status: "pending" }));
    setRows((existing) => [...existing, ...next]);
  }

  async function uploadAll() {
    for (let index = 0; index < rows.length; index += 1) {
      if (rows[index].status !== "pending") continue;
      setRows((existing) =>
        existing.map((row, i) => (i === index ? { ...row, status: "uploading" } : row)),
      );
      try {
        const result = await uploadResume(requisitionId, rows[index].file);
        setRows((existing) =>
          existing.map((row, i) =>
            i === index ? { ...row, status: "uploaded", resumeId: result.id } : row,
          ),
        );
      } catch (cause) {
        setRows((existing) =>
          existing.map((row, i) =>
            i === index
              ? {
                  ...row,
                  status: "error",
                  error: cause instanceof Error ? cause.message : "Upload failed",
                }
              : row,
          ),
        );
      }
    }
  }

  async function scoreAll() {
    setScoringAll(true);
    setScoringError(null);
    try {
      const profile = await createWeightProfile(requisitionId, {
        name: "Default",
        weights: DEFAULT_WEIGHTS,
        auto_reject_below: 30,
        hold_below: 50,
        highly_recommended_at: 85,
      });
      for (let index = 0; index < rows.length; index += 1) {
        const row = rows[index];
        if (row.status !== "uploaded" || !row.resumeId) continue;
        setRows((existing) =>
          existing.map((r, i) => (i === index ? { ...r, status: "scoring" } : r)),
        );
        try {
          const result = await runScoring(requisitionId, row.resumeId, profile.id);
          setRows((existing) =>
            existing.map((r, i) =>
              i === index
                ? {
                    ...r,
                    status: "scored",
                    score: result.total_score,
                    verdict: result.verdict,
                  }
                : r,
            ),
          );
        } catch (cause) {
          setRows((existing) =>
            existing.map((r, i) =>
              i === index
                ? {
                    ...r,
                    status: "error",
                    error: cause instanceof Error ? cause.message : "Scoring failed",
                  }
                : r,
            ),
          );
        }
      }
    } catch (cause) {
      setScoringError(
        cause instanceof Error ? cause.message : "Failed to create a scoring profile",
      );
    } finally {
      setScoringAll(false);
    }
  }

  const anyUploaded = rows.some((row) => row.status === "uploaded" || row.status === "scored");
  const anyPending = rows.some((row) => row.status === "pending");

  return (
    <main className="mx-auto max-w-3xl px-6 py-10 text-[var(--mist)]">
      <header className="mb-8">
        <Link
          to={`/requisitions/${requisitionId}`}
          className="text-xs text-[var(--haze)] hover:text-[var(--signal-text)]"
        >
          ← Requisition
        </Link>
        <h1 className="display mt-1 text-2xl font-semibold">Upload resumes</h1>
        <p className="mt-1 text-sm text-[var(--haze)]">
          PDF, DOCX, or plain text. Up to 10MB each.
        </p>
      </header>

      {scoringError ? (
        <Card className="mb-6">
          <p role="alert" className="text-sm text-[var(--danger)]">
            {scoringError}
          </p>
        </Card>
      ) : null}

      <Card className="mb-6">
        <div
          className="flex flex-col items-center gap-3 rounded-[var(--radius-md)] border border-dashed border-[var(--steel)] px-6 py-10 text-center"
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            event.preventDefault();
            addFiles(event.dataTransfer.files);
          }}
        >
          <p className="text-sm text-[var(--haze)]">Drag files here, or</p>
          <Button variant="ghost" onClick={() => inputRef.current?.click()}>
            Choose files
          </Button>
          <input
            ref={inputRef}
            type="file"
            multiple
            accept=".pdf,.docx,.txt"
            className="hidden"
            onChange={(event) => addFiles(event.target.files)}
          />
        </div>
      </Card>

      {rows.length > 0 ? (
        <Card className="mb-6">
          <ul className="flex flex-col gap-3">
            {rows.map((row, index) => (
              <li
                key={`${row.file.name}-${index}`}
                className="flex items-center justify-between gap-3 border-b border-[var(--steel)] pb-3 last:border-0 last:pb-0"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{row.file.name}</p>
                  {row.error ? (
                    <p className="text-xs text-[var(--danger)]">{row.error}</p>
                  ) : null}
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  {row.status === "scored" && row.score !== undefined ? (
                    <>
                      <span className="data-value text-sm font-semibold">{row.score}</span>
                      <Badge tone={VERDICT_TONE[row.verdict ?? ""] ?? "neutral"}>
                        {row.verdict}
                      </Badge>
                    </>
                  ) : (
                    <Badge
                      tone={
                        row.status === "error"
                          ? "negative"
                          : row.status === "uploaded"
                            ? "positive"
                            : "neutral"
                      }
                    >
                      {row.status}
                    </Badge>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      <div className="flex flex-wrap gap-3">
        <Button
          onClick={() => {
            void uploadAll();
          }}
          disabled={!anyPending}
          arrow
        >
          Upload all
        </Button>
        <Button
          variant="ghost"
          onClick={() => {
            void scoreAll();
          }}
          disabled={!anyUploaded || scoringAll}
        >
          {scoringAll ? "Scoring…" : "Score uploaded resumes"}
        </Button>
        <Link
          to={`/pipeline?req=${requisitionId}`}
          className="ml-auto self-center text-sm text-[var(--signal-text)] hover:underline"
        >
          View pipeline →
        </Link>
      </div>
    </main>
  );
}
