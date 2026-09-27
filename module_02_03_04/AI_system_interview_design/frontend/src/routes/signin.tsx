import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Layers } from "lucide-react";
import { ApiError, register, signIn } from "@/lib/api";
import { loadAuth, saveAuth, saveHostName } from "@/lib/identity";

export const Route = createFileRoute("/signin")({
  head: () => ({
    meta: [
      { title: "Interviewer sign-in — Loopboard" },
      {
        name: "description",
        content: "Sign in to create interview sessions and revisit past boards.",
      },
      { property: "og:title", content: "Interviewer sign-in — Loopboard" },
      { property: "og:description", content: "Sign in to run system design interviews." },
    ],
  }),
  component: SignInPage,
});

type Mode = "signin" | "register";

function SignInPage() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Already signed in? Nothing to do here.
  useEffect(() => {
    if (loadAuth()) void navigate({ to: "/", replace: true });
  }, [navigate]);

  async function submit() {
    if (busy || !email.trim() || !password) return;
    setBusy(true);
    setError(null);
    try {
      const auth =
        mode === "signin"
          ? await signIn({ email: email.trim(), password })
          : await register({ email: email.trim(), password, name: name.trim() });
      saveAuth(auth);
      if (auth.interviewer.name) saveHostName(auth.interviewer.name);
      void navigate({ to: "/", replace: true });
    } catch (cause) {
      setError(
        cause instanceof ApiError ? cause.message : "Something went wrong. Is the API running?",
      );
      setBusy(false);
    }
  }

  const registering = mode === "register";

  return (
    <main className="flex min-h-screen items-center justify-center px-5">
      <div className="panel w-full max-w-md p-6">
        <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <Layers className="h-5 w-5" />
        </span>
        <h1 className="mt-5 text-xl font-semibold">
          {registering ? "Create an interviewer account" : "Interviewer sign-in"}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Candidates don't need an account — they join with a link and a display name.
        </p>

        {registering && (
          <label className="mt-6 block">
            <span className="label-caps">Your name</span>
            <input
              className="field mt-1"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Alex Rivera"
            />
          </label>
        )}

        <label className="mt-4 block">
          <span className="label-caps">Email</span>
          <input
            autoFocus
            type="email"
            autoComplete="username"
            className="field mt-1"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void submit()}
            placeholder="alex@loopboard.dev"
          />
        </label>

        <label className="mt-4 block">
          <span className="label-caps">Password</span>
          <input
            type="password"
            autoComplete={registering ? "new-password" : "current-password"}
            className="field mt-1"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void submit()}
            placeholder={registering ? "at least 8 characters" : "••••••••"}
          />
        </label>

        {error && <p className="mt-4 text-sm text-destructive">{error}</p>}

        <button
          type="button"
          className="btn-base btn-primary mt-6 w-full"
          onClick={submit}
          disabled={busy}
        >
          {busy ? "Working…" : registering ? "Create account" : "Sign in"}
        </button>

        <button
          type="button"
          className="btn-base btn-ghost mt-2 w-full"
          onClick={() => {
            setMode(registering ? "signin" : "register");
            setError(null);
          }}
        >
          {registering ? "I already have an account" : "Create an account instead"}
        </button>

        <p className="mt-5 font-mono text-xs text-muted-foreground">
          The backend ships with seeded demo data: alex@loopboard.dev / loopboard-demo
        </p>
      </div>
    </main>
  );
}
