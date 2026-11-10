import { useCallback, useEffect, useState } from "react";

import { ApiError } from "@/api/client";
import { fetchMe, type Me } from "@/api/me";
import { AuthProvider } from "@/auth/AuthProvider";
import type { AuthClient } from "@/auth/client";
import { useAuth } from "@/auth/context";
import { AppShell } from "@/components/AppShell";
import { StatusCard } from "@/components/StatusCard";
import { Button } from "@/components/ui/button";
import { ProjectsPage } from "@/pages/ProjectsPage";

type MeState =
  | { status: "loading" }
  | { status: "ready"; me: Me }
  | { status: "forbidden" }
  | { status: "error" };

function SignedIn() {
  const { api, signIn, signOut } = useAuth();
  const [state, setState] = useState<MeState>({ status: "loading" });

  const load = useCallback(async () => {
    setState({ status: "loading" });
    try {
      setState({ status: "ready", me: await fetchMe(api) });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return signIn(); // session ended
      setState({ status: err instanceof ApiError && err.status === 403 ? "forbidden" : "error" });
    }
  }, [api, signIn]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial data load on mount
    void load();
  }, [load]);

  switch (state.status) {
    case "ready":
      return (
        <AppShell me={state.me} onSignOut={signOut} page="Projects">
          <ProjectsPage />
        </AppShell>
      );
    case "loading":
      return <StatusCard busy title="Signing you in" body="Loading your account…" />;
    case "forbidden":
      return (
        <StatusCard
          title="Your account can't be used"
          body="Your account is not active, or your partner has been suspended. Ask your partner admin for help."
        >
          <Button variant="outline" onClick={signOut}>
            Sign out
          </Button>
        </StatusCard>
      );
    case "error":
      return (
        <StatusCard title="Something went wrong" body="We couldn't load your account. Please try again.">
          <Button onClick={() => void load()}>Try again</Button>
          <Button variant="outline" onClick={signOut}>
            Sign out
          </Button>
        </StatusCard>
      );
  }
}

interface AppProps {
  client: AuthClient | null;
  redirect?: (url: string) => void;
  fetchImpl?: typeof fetch;
  designPreview?: boolean;
}

export default function App({ client, redirect, fetchImpl, designPreview }: AppProps) {
  return (
    <AuthProvider
      client={client}
      redirect={redirect}
      fetchImpl={fetchImpl}
      designPreview={designPreview}
    >
      <SignedIn />
    </AuthProvider>
  );
}
