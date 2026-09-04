import { useEffect, useState } from "react";
import { Button, Card, Field, Input } from "@aiva/ui";
import { activateMfa, enrollMfa, type MfaEnrollResponse } from "../api/client";

export function MfaSetupPage() {
  const [enrollment, setEnrollment] = useState<MfaEnrollResponse | null>(null);
  const [code, setCode] = useState("");
  const [status, setStatus] = useState<"idle" | "enrolling" | "activating" | "done">("idle");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    document.title = "AIVA — Two-factor setup";
  }, []);

  async function startEnrollment() {
    setStatus("enrolling");
    setError(null);
    try {
      const result = await enrollMfa();
      setEnrollment(result);
      setStatus("idle");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Failed to start enrollment");
      setStatus("idle");
    }
  }

  async function submitCode(event: React.FormEvent) {
    event.preventDefault();
    setStatus("activating");
    setError(null);
    try {
      await activateMfa(code);
      setStatus("done");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Invalid code");
      setStatus("idle");
    }
  }

  return (
    <main className="mx-auto max-w-lg px-6 py-10 text-[var(--mist)]">
      <header className="mb-8">
        <h1 className="display text-2xl font-semibold">Two-factor authentication</h1>
        <p className="mt-1 text-sm text-[var(--haze)]">
          Adds a 6-digit code from an authenticator app to every sign-in.
        </p>
      </header>

      {error ? (
        <Card className="mb-6">
          <p role="alert" className="text-sm text-[var(--danger)]">
            {error}
          </p>
        </Card>
      ) : null}

      {status === "done" ? (
        <Card>
          <p className="font-medium text-[var(--success)]">Two-factor authentication is now active.</p>
          <p className="mt-2 text-sm text-[var(--haze)]">
            You'll be asked for a code the next time you sign in.
          </p>
        </Card>
      ) : !enrollment ? (
        <Card>
          <p className="mb-4 text-sm text-[var(--haze)]">
            You'll need an authenticator app (Google Authenticator, 1Password, Authy, or
            similar) on your phone.
          </p>
          <Button onClick={() => void startEnrollment()} disabled={status === "enrolling"} arrow>
            {status === "enrolling" ? "Starting…" : "Start setup"}
          </Button>
        </Card>
      ) : (
        <Card>
          <p className="mb-3 text-sm">
            Add this account to your authenticator app. If it can't scan a QR code, enter
            this key manually:
          </p>
          <p className="mono mb-4 break-all rounded-[var(--radius-md)] border border-[var(--steel)] bg-[var(--abyss)] px-3 py-2 text-sm">
            {enrollment.secret}
          </p>
          <details className="mb-4">
            <summary className="cursor-pointer text-xs text-[var(--haze)]">
              Show setup URI
            </summary>
            <p className="mono mt-2 break-all text-xs text-[var(--haze)]">
              {enrollment.otpauth_uri}
            </p>
          </details>
          <form
            onSubmit={(event) => {
              void submitCode(event);
            }}
            className="flex flex-col gap-4"
          >
            <Field
              label="Enter the 6-digit code from your app"
              htmlFor="mfa-code"
              hint="Confirms the setup worked before we require it every time"
            >
              <Input
                id="mfa-code"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                required
                value={code}
                onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))}
              />
            </Field>
            <Button type="submit" disabled={status === "activating"} arrow>
              {status === "activating" ? "Verifying…" : "Activate"}
            </Button>
          </form>
        </Card>
      )}
    </main>
  );
}
