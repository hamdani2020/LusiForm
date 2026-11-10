import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import type { Me } from "@/api/me";
import App from "@/App";
import { AuthClient } from "@/auth/client";
import type { AuthConfig } from "@/auth/config";

export const config: AuthConfig = {
  domain: "https://auth.example.com",
  clientId: "client-123",
  redirectUri: "http://localhost:3000/auth/callback",
  logoutUri: "http://localhost:3000/",
  scopes: "openid email",
};

export const ACCESS = "access-token-1";
export const REFRESH = "refresh-token-1";

export function meFor(overrides: Partial<Me> = {}): Me {
  return {
    user_id: "11111111-1111-1111-1111-111111111111",
    partner_id: "22222222-2222-2222-2222-222222222222",
    partner_name: "Acme Cloud Solutions",
    email: "casey@example.com",
    display_name: "Casey Consultant",
    roles: ["consultant"],
    ...overrides,
  };
}

export interface Call {
  url: string;
  init?: RequestInit;
}

type Handler = (call: Call) => Response | Promise<Response>;

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** A fake fetch that records calls and answers the token endpoint and /api/me. */
export function fakeFetch(handlers: { me?: Handler; token?: Handler } = {}) {
  const calls: Call[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const call = { url, init };
    calls.push(call);
    if (url.endsWith("/oauth2/token")) {
      return handlers.token
        ? handlers.token(call)
        : json({ access_token: ACCESS, refresh_token: REFRESH, expires_in: 3600 });
    }
    if (url.endsWith("/api/me")) {
      return handlers.me ? handlers.me(call) : json(meFor());
    }
    return json({ detail: "unexpected" }, 500);
  });
  return { fn: fn as unknown as typeof fetch, calls };
}

export function makeClient(fetchFn: typeof fetch, now?: () => number): AuthClient {
  return new AuthClient(config, { fetch: fetchFn, storage: window.sessionStorage, now });
}

export function renderApp(
  client: AuthClient | null,
  redirect = vi.fn(),
  fetchImpl?: typeof fetch,
  designPreview?: boolean,
) {
  return {
    redirect,
    ...render(
      <App
        client={client}
        redirect={redirect}
        fetchImpl={fetchImpl}
        designPreview={designPreview}
      />,
    ),
  };
}

/** Click the landing page's first "Sign in" button (the header one). */
export function clickSignIn() {
  fireEvent.click(screen.getAllByRole("button", { name: "Sign in" })[0]);
}

/**
 * Run the two halves of a real sign-in: visit "/" and click "Sign in" on the landing page
 * (captures the redirect to the hosted login), then come back on the callback URL with a
 * code and the matching state.
 */
export async function signInThroughCallback(fetchFn: typeof fetch, now?: () => number) {
  window.history.pushState(null, "", "/");
  const first = renderApp(makeClient(fetchFn, now), vi.fn(), fetchFn);
  clickSignIn();
  await waitFor(() => expect(first.redirect).toHaveBeenCalled());
  const authorizeUrl = new URL(first.redirect.mock.calls[0][0] as string);
  first.unmount();

  const state = authorizeUrl.searchParams.get("state") ?? "";
  window.history.pushState(null, "", `/auth/callback?code=the-code&state=${state}`);
  return { authorizeUrl, ...renderApp(makeClient(fetchFn, now), undefined, fetchFn) };
}
