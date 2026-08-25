import { Button, Card, EmptyState, Field, Input, PageStagger } from "@aiva/ui";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

export default function Join() {
  const navigate = useNavigate();
  const [token, setToken] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    return params.get("token") ?? "";
  });
  const trimmed = token.trim();

  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-8 px-6 py-12">
      <PageStagger>
        <Card>
          <p className="text-sm uppercase tracking-widest text-[var(--haze)]">Step 1 of 3</p>
          <h1 className="display mt-2 text-2xl font-bold">Open your interview link</h1>
          <p className="mt-3 leading-relaxed text-[var(--mist)]">
            Paste the personal interview token from your invitation. It opens your session —
            nothing about you is stored before your hiring team invites you.
          </p>
          <form
            className="mt-6 flex flex-col gap-4"
            onSubmit={(event) => {
              event.preventDefault();
              if (!trimmed) return;
              navigate("/interview", { state: { token: trimmed } });
            }}
          >
            <Field label="Interview token" hint="Shown once by your recruiter" htmlFor="join-token">
              <Input
                id="join-token"
                value={token}
                onChange={(event) => setToken(event.target.value)}
                placeholder="Paste your token"
                autoFocus
              />
            </Field>
            <Button type="submit" disabled={trimmed.length === 0}>
              Begin equipment check
            </Button>
          </form>
        </Card>

        <EmptyState
          title="What to expect"
          body="You will confirm recording consent, run a camera / microphone / speaker check, then start the guided interview. Your answers are transcribed locally; the interviewer reviews them afterwards."
        />
      </PageStagger>
    </main>
  );
}
