import { useCallback, useEffect, useState, type ComponentType, type ReactNode } from "react";
import { Button, Input, Text } from "@cloudflare/kumo";

import { bootstrapAuth, getAuthStatus, getMe, getOverview, loginAuth, logoutAuth, type AuthStatus, type AuthUser } from "./api";
import { Logo } from "./components/Logo";
import { OperatorProvider, ToastProvider } from "./governance";
import { useApi } from "./hooks";
import { Shell } from "./Shell";
import { useRoute, type Route } from "./router";

import { Overview } from "./views/Overview";
import { Scoring } from "./views/Scoring";
import { Storage } from "./views/Storage";
import { Models } from "./views/Models";
import { Drift } from "./views/Drift";
import { Healing } from "./views/Healing";
import { Governance } from "./views/Governance";
import { Feedback } from "./views/Feedback";
import { Benchmarks } from "./views/Benchmarks";

const VIEWS: Record<Route, ComponentType> = {
  overview: Overview,
  scoring: Scoring,
  storage: Storage,
  models: Models,
  drift: Drift,
  healing: Healing,
  governance: Governance,
  feedback: Feedback,
  benchmarks: Benchmarks,
};

export function App() {
  return (
    <ToastProvider>
      <AuthGate />
    </ToastProvider>
  );
}

function AuthGate() {
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const authStatus = await getAuthStatus();
      setStatus(authStatus);
      if (authStatus.users_configured) {
        try {
          const me = await getMe();
          setUser(me.user);
        } catch {
          setUser(null);
        }
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const logout = useCallback(async () => {
    await logoutAuth();
    setUser(null);
    await load();
  }, [load]);

  if (loading && !status) {
    return <AuthShell title="Loading Tenta" />;
  }
  if (status?.needs_bootstrap) {
    return <AuthForm mode="bootstrap" onDone={setUser} />;
  }
  if (!user) {
    return <AuthForm mode="login" onDone={setUser} />;
  }
  return (
    <OperatorProvider user={user} onLogout={logout}>
      <ConsoleApp />
    </OperatorProvider>
  );
}

function AuthShell({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <main className="auth-screen">
      <section className="auth-panel">
        <div className="auth-brand">
          <span className="brand-mark">
            <Logo size={28} />
          </span>
          <div>
            <h1>{title}</h1>
            <p>Tenta Decision Runtime</p>
          </div>
        </div>
        {children}
      </section>
    </main>
  );
}

function AuthForm({ mode, onDone }: { mode: "bootstrap" | "login"; onDone: (user: AuthUser) => void }) {
  const [email, setEmail] = useState("admin@tenta.local");
  const [displayName, setDisplayName] = useState("Administrator");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bootstrap = mode === "bootstrap";

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = bootstrap
        ? await bootstrapAuth({ email, password, display_name: displayName })
        : await loginAuth({ email, password });
      onDone(result.user);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthShell title={bootstrap ? "Create the first admin" : "Sign in"}>
      <form className="auth-form" onSubmit={submit}>
        <Input label="Email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
        {bootstrap && (
          <Input label="Display name" value={displayName} onChange={(event) => setDisplayName(event.target.value)} required />
        )}
        <Input label="Password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} required />
        {error && <Text variant="error" size="sm">{error}</Text>}
        <Button type="submit" variant="primary" loading={busy}>
          {bootstrap ? "Create admin" : "Sign in"}
        </Button>
      </form>
    </AuthShell>
  );
}

function ConsoleApp() {
  const route = useRoute();
  const { data: overview } = useApi(getOverview, 5000);
  const [mode, setMode] = useState<"light" | "dark">(() =>
    document.documentElement.dataset.mode === "dark" ? "dark" : "light",
  );

  const toggleTheme = useCallback(() => {
    setMode((current) => {
      const next = current === "dark" ? "light" : "dark";
      document.documentElement.dataset.mode = next;
      return next;
    });
  }, []);

  const View = VIEWS[route] ?? Overview;

  return (
    <Shell overview={overview} mode={mode} onToggleTheme={toggleTheme}>
      <View />
    </Shell>
  );
}
