import { useEffect, useState } from "react";
import { Navigate, useSearchParams } from "react-router-dom";
import { Button, Card, Field, Input } from "@aiva/ui";
import { ApiError, login } from "../api/client";
import { useAuth, signIn } from "../auth";

export function LoginPage() {
  const auth = useAuth();
  const [params] = useSearchParams();
  const next = params.get("next") ?? "/";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [needsTotp, setNeedsTotp] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    document.title = "AIVA — Sign in";
  }, []);

  if (auth.token) {
    return <Navigate to={next} replace />;
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const response = await login(email, password, needsTotp ? totpCode : undefined);
      signIn(response.access_token);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        // The backend distinguishes "hasn't entered a code yet" from "the
        // code was wrong" in its error detail -- both are 401, so the
        // message text is what tells them apart.
        if (cause.message.includes("TOTP code required")) {
          setNeedsTotp(true);
          setError(null);
          return;
        }
        if (cause.message.includes("Invalid TOTP code")) {
          setNeedsTotp(true);
          setError("Incorrect code — try again.");
          return;
        }
      }
      setError(cause instanceof Error ? cause.message : "Sign-in failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="grid min-h-screen place-items-center bg-[var(--abyss)] px-6 text-[var(--mist)]">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <span className="display text-2xl font-bold tracking-tight text-[var(--signal)]">
            AIVA
          </span>
          <p className="mt-2 text-sm text-[var(--haze)]">Practical AI for hiring teams.</p>
        </div>
        <Card>
          <h1 className="display mb-1 text-xl font-semibold">
            {needsTotp ? "Enter your code" : "Sign in to the console"}
          </h1>
          <p className="mb-6 text-xs text-[var(--haze)]">
            {needsTotp
              ? "Open your authenticator app and enter the 6-digit code."
              : "MFA-protected accounts will be prompted for a code after this step."}
          </p>
          <form
              onSubmit={(event) => {
                void submit(event);
              }}
              className="flex flex-col gap-4"
            >
            {!needsTotp ? (
              <>
                <Field label="Work email" htmlFor="email">
                  <Input
                    id="email"
                    type="email"
                    autoComplete="username"
                    required
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                  />
                </Field>
                <Field label="Password" htmlFor="password" error={error ?? undefined}>
                  <Input
                    id="password"
                    type="password"
                    autoComplete="current-password"
                    required
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                  />
                </Field>
              </>
            ) : (
              <Field
                label="Authentication code"
                htmlFor="totp"
                error={error ?? undefined}
                hint="6 digits, refreshes every 30 seconds"
              >
                <Input
                  id="totp"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  autoFocus
                  maxLength={6}
                  required
                  value={totpCode}
                  onChange={(event) => setTotpCode(event.target.value.replace(/\D/g, ""))}
                />
              </Field>
            )}
            <Button type="submit" disabled={busy} arrow className="mt-2 w-full">
              {busy ? "Signing in…" : needsTotp ? "Verify" : "Sign in"}
            </Button>
            {needsTotp ? (
              <Button
                type="button"
                variant="ghost"
                onClick={() => {
                  setNeedsTotp(false);
                  setTotpCode("");
                  setError(null);
                }}
              >
                ← Back
              </Button>
            ) : null}
          </form>
        </Card>
      </div>
    </main>
  );
}
