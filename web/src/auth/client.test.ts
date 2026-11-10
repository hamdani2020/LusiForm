import { beforeEach, describe, expect, it } from "vitest";

import { AuthClient } from "@/auth/client";
import { loadAuthConfig } from "@/auth/config";
import { fakeFetch, json, config } from "@/test/helpers";

beforeEach(() => window.sessionStorage.clear());

async function signedInClient(now: { t: number }, handlers: Parameters<typeof fakeFetch>[0] = {}) {
  const f = fakeFetch(handlers);
  const client = new AuthClient(config, {
    fetch: f.fn,
    storage: window.sessionStorage,
    now: () => now.t,
  });
  const url = new URL(await client.createAuthorizeUrl());
  await client.handleCallback(`?code=c&state=${url.searchParams.get("state")}`);
  return { client, ...f };
}

describe("AuthClient", () => {
  it("keeps tokens in memory and returns the access token", async () => {
    const now = { t: 1_000 };
    const { client } = await signedInClient(now);
    expect(client.isAuthenticated()).toBe(true);
    expect(await client.getAccessToken()).toBe("access-token-1");
  });

  it("refreshes shortly before the access token expires", async () => {
    const now = { t: 0 };
    const { client, calls } = await signedInClient(now, {
      token: ({ init }) =>
        new URLSearchParams(String(init?.body)).get("grant_type") === "refresh_token"
          ? json({ access_token: "fresh", expires_in: 3600 })
          : json({ access_token: "first", refresh_token: "r1", expires_in: 3600 }),
    });
    expect(await client.getAccessToken()).toBe("first");
    now.t = 3_600_000 - 30_000; // inside the 60 s margin
    expect(await client.getAccessToken()).toBe("fresh");
    expect(calls.filter((c) => c.url.endsWith("/oauth2/token"))).toHaveLength(2);
  });

  it("shares one refresh between concurrent callers", async () => {
    const now = { t: 0 };
    const { client, calls } = await signedInClient(now);
    now.t = 3_600_000;
    await Promise.all([client.getAccessToken(), client.getAccessToken(), client.getAccessToken()]);
    const refreshes = calls.filter((c) =>
      String(c.init?.body).includes("grant_type=refresh_token"),
    );
    expect(refreshes).toHaveLength(1);
  });

  it("clears the session when the refresh token is rejected", async () => {
    const now = { t: 0 };
    const { client } = await signedInClient(now, {
      token: ({ init }) =>
        new URLSearchParams(String(init?.body)).get("grant_type") === "refresh_token"
          ? json({ error: "invalid_grant" }, 400)
          : json({ access_token: "first", refresh_token: "r1", expires_in: 3600 }),
    });
    expect(await client.refresh()).toBe(false);
    expect(client.isAuthenticated()).toBe(false);
    expect(await client.getAccessToken()).toBeNull();
  });

  it("exchanges an authorization code only once, even if the callback is handled twice", async () => {
    const f = fakeFetch();
    const client = new AuthClient(config, { fetch: f.fn, storage: window.sessionStorage });
    const url = new URL(await client.createAuthorizeUrl());
    const search = `?code=c&state=${url.searchParams.get("state")}`;
    await Promise.all([client.handleCallback(search), client.handleCallback(search)]);
    expect(f.calls.filter((c) => c.url.endsWith("/oauth2/token"))).toHaveLength(1);
  });

  it("creates a single verifier and state per redirect", async () => {
    const f = fakeFetch();
    const client = new AuthClient(config, { fetch: f.fn, storage: window.sessionStorage });
    const [a, b] = await Promise.all([client.createAuthorizeUrl(), client.createAuthorizeUrl()]);
    expect(a).toBe(b);
  });
});

describe("loadAuthConfig", () => {
  const origin = "http://localhost:5173";

  it("builds the config from env", () => {
    const cfg = loadAuthConfig(
      { VITE_COGNITO_DOMAIN: "https://x.auth.us-east-1.amazoncognito.com/", VITE_COGNITO_CLIENT_ID: "abc" },
      origin,
    );
    expect(cfg).toEqual({
      domain: "https://x.auth.us-east-1.amazoncognito.com",
      clientId: "abc",
      redirectUri: "http://localhost:5173/auth/callback",
      logoutUri: "http://localhost:5173/",
      scopes: "openid email",
    });
  });

  it("accepts a bare domain and assumes https", () => {
    const cfg = loadAuthConfig(
      { VITE_COGNITO_DOMAIN: "x.auth.us-east-1.amazoncognito.com", VITE_COGNITO_CLIENT_ID: "abc" },
      origin,
    );
    expect(cfg?.domain).toBe("https://x.auth.us-east-1.amazoncognito.com");
  });

  it.each([
    ["missing domain", { VITE_COGNITO_CLIENT_ID: "abc" }],
    ["missing client id", { VITE_COGNITO_DOMAIN: "https://x.example.com" }],
    ["empty values", { VITE_COGNITO_DOMAIN: " ", VITE_COGNITO_CLIENT_ID: "" }],
    ["plain http", { VITE_COGNITO_DOMAIN: "http://x.example.com", VITE_COGNITO_CLIENT_ID: "abc" }],
  ])("returns null for %s", (_name, env) => {
    expect(loadAuthConfig(env, origin)).toBeNull();
  });
});
