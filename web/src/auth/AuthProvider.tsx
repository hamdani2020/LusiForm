import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { createApi } from "@/api/client";
import { StatusCard } from "@/components/StatusCard";
import { LandingPage } from "@/pages/LandingPage";

import type { AuthClient } from "./client";
import { CALLBACK_PATH } from "./config";
import { AuthContext, type AuthContextValue } from "./context";

type Status = "signed-out" | "callback" | "redirecting" | "authenticated" | "error";

interface AuthProviderProps {
  /** Null when Cognito is not configured; the app then explains that instead of redirecting. */
  client: AuthClient | null;
  children: ReactNode;
  /** Navigation hook so tests can observe the redirect. Defaults to a full-page navigation. */
  redirect?: (url: string) => void;
  /** fetch used for API calls. Defaults to the global fetch. */
  fetchImpl?: typeof fetch;
  /**
   * When Cognito is not configured, let "Sign in" open a non-functional preview of the
   * Sign In design. Defaults to development builds only; production builds never show it.
   */
  designPreview?: boolean;
}

// Dev builds only: Vite replaces import.meta.env.DEV with false in production builds, so
// the preview module is dropped from the production bundle entirely.
const SignInPreview = import.meta.env.DEV
  ? lazy(() => import("@/pages/SignInPreview").then((m) => ({ default: m.SignInPreview })))
  : null;

function defaultRedirect(url: string): void {
  window.location.assign(url);
}

function initialStatus(client: AuthClient | null): Status {
  if (!client) return "signed-out";
  if (window.location.pathname === CALLBACK_PATH) return "callback";
  return client.isAuthenticated() ? "authenticated" : "signed-out";
}

/**
 * Gate for the whole app.
 *
 * - Signed out: the public landing page. Its "Sign in" sends the user to the Cognito
 *   hosted login (authorization code + PKCE).
 * - On the callback URL: exchange the code (tokens stay in memory), then render children.
 * - A session that ends mid-use (refresh rejected) goes straight back to the hosted login.
 */
export function AuthProvider({
  client,
  children,
  redirect = defaultRedirect,
  fetchImpl,
  designPreview: designPreviewProp = import.meta.env.DEV,
}: AuthProviderProps) {
  const [status, setStatus] = useState<Status>(() => initialStatus(client));
  const [previewOpen, setPreviewOpen] = useState(false);
  const designPreview = designPreviewProp && SignInPreview !== null;
  const [message, setMessage] = useState("");

  const signIn = useCallback(() => {
    if (!client) return;
    setStatus("redirecting");
    client.clear();
    client
      .createAuthorizeUrl()
      .then(redirect)
      .catch(() => {
        setMessage("Could not start sign-in. Please try again.");
        setStatus("error");
      });
  }, [client, redirect]);

  useEffect(() => {
    if (!client || status !== "callback") return;
    let cancelled = false;
    client
      .handleCallback(window.location.search)
      .then(() => {
        if (!cancelled) setStatus("authenticated");
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setMessage(err instanceof Error ? err.message : "Sign-in failed.");
        setStatus("error");
      })
      .finally(() => {
        // Drop ?code=&state= from the address bar and history either way.
        window.history.replaceState(null, "", "/");
      });
    return () => {
      cancelled = true;
    };
  }, [client, status]);

  const value = useMemo<AuthContextValue | null>(() => {
    if (!client) return null;
    return {
      api: createApi(client, fetchImpl),
      signIn,
      signOut: () => {
        client.clear();
        redirect(client.logoutUrl());
      },
    };
  }, [client, fetchImpl, redirect, signIn]);

  if (!client) {
    if (designPreview && previewOpen && SignInPreview) {
      return (
        <Suspense fallback={<StatusCard busy title="Sign in" body="Loading the preview…" />}>
          <SignInPreview onBack={() => setPreviewOpen(false)} />
        </Suspense>
      );
    }
    return (
      <LandingPage
        onSignIn={designPreview ? () => setPreviewOpen(true) : undefined}
        message={{
          title: "Sign-in is not configured",
          body: designPreview ? `${MISCONFIGURED} ${PREVIEW_NOTE}` : MISCONFIGURED,
        }}
      />
    );
  }
  if (status === "authenticated" && value) {
    return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
  }
  if (status === "signed-out") return <LandingPage onSignIn={signIn} />;
  if (status === "error") {
    return (
      <LandingPage onSignIn={signIn} message={{ title: "We couldn't sign you in", body: message }} />
    );
  }
  return (
    <StatusCard
      busy
      title="Signing you in"
      body={status === "redirecting" ? "Taking you to the sign-in page…" : "Finishing sign-in…"}
    />
  );
}

const MISCONFIGURED =
  "This environment has no Cognito hosted login configured. Set VITE_COGNITO_DOMAIN and " +
  "VITE_COGNITO_CLIENT_ID (see .env.example) and restart the web service.";

const PREVIEW_NOTE = "Until then, Sign in opens a preview of the sign-in page design.";
