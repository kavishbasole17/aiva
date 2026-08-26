import { useEffect, useState } from "react";
import { Navigate, useSearchParams } from "react-router-dom";
import { Button, Card, Field, Input } from "@aiva/ui";
import { login } from "../api/client";
import { useAuth, signIn } from "../auth";

export function LoginPage() {
  const auth = useAuth();
  const [params] = useSearchParams();
  const next = params.get("next") ?? "/";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
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
      const response = await login(email, password);
      signIn(response.access_token);
    } catch (cause) {
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
          <h1 className="display mb-1 text-xl font-semibold">Sign in to the console</h1>
          <p className="mb-6 text-xs text-[var(--haze)]">
            MFA-protected accounts will be prompted for a code in a later milestone.
          </p>
          <form
              onSubmit={(event) => {
                void submit(event);
              }}
              className="flex flex-col gap-4"
            >
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
            <Button type="submit" disabled={busy} arrow className="mt-2 w-full">
              {busy ? "Signing in…" : "Sign in"}
            </Button>
          </form>
        </Card>
      </div>
    </main>
  );
}
