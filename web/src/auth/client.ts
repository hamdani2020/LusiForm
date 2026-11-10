/**
 * Cognito hosted-login client: authorization code flow with PKCE, public client.
 *
 * Tokens live in memory only. Nothing long-lived is written to the browser: the PKCE
 * verifier and state sit in sessionStorage for the length of one redirect and are
 * removed as soon as the callback is handled. After a page reload there are no tokens
 * in memory, so the app redirects to the hosted login, whose own session cookie signs
 * the user straight back in without asking for the password again.
 */

import type { AuthConfig } from "./config";
import { challengeFor, randomString } from "./pkce";

const VERIFIER_KEY = "lusiform.pkce.verifier";
const STATE_KEY = "lusiform.pkce.state";
const REFRESH_MARGIN_MS = 60_000;

export class AuthError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AuthError";
  }
}

interface TokenSet {
  accessToken: string;
  refreshToken: string | null;
  expiresAt: number; // epoch ms
}

interface TokenResponse {
  access_token?: string;
  refresh_token?: string;
  expires_in?: number;
  error?: string;
}

export interface AuthDeps {
  fetch: typeof fetch;
  storage: Pick<Storage, "getItem" | "setItem" | "removeItem">;
  now: () => number;
}

export class AuthClient {
  private tokens: TokenSet | null = null;
  private refreshing: Promise<boolean> | null = null;
  private authorizeUrl: Promise<string> | null = null;
  private callback: { search: string; promise: Promise<void> } | null = null;
  private readonly deps: AuthDeps;

  constructor(
    private readonly config: AuthConfig,
    deps: Partial<AuthDeps> = {},
  ) {
    this.deps = {
      fetch: deps.fetch ?? ((...args) => globalThis.fetch(...args)),
      storage: deps.storage ?? window.sessionStorage,
      now: deps.now ?? Date.now,
    };
  }

  isAuthenticated(): boolean {
    return this.tokens !== null;
  }

  /** Build the hosted-login URL and remember the PKCE verifier and state for the callback. */
  createAuthorizeUrl(): Promise<string> {
    // Memoised so React StrictMode's double effect cannot store two different verifiers.
    this.authorizeUrl ??= (async () => {
      const verifier = randomString(48);
      const state = randomString(16);
      this.deps.storage.setItem(VERIFIER_KEY, verifier);
      this.deps.storage.setItem(STATE_KEY, state);
      const params = new URLSearchParams({
        response_type: "code",
        client_id: this.config.clientId,
        redirect_uri: this.config.redirectUri,
        scope: this.config.scopes,
        state,
        code_challenge_method: "S256",
        code_challenge: await challengeFor(verifier),
      });
      return `${this.config.domain}/oauth2/authorize?${params.toString()}`;
    })();
    return this.authorizeUrl;
  }

  /** Handle `?code=...&state=...` on the callback URL and keep the tokens in memory. */
  handleCallback(search: string): Promise<void> {
    // Memoised per URL: an authorization code can be exchanged only once.
    if (this.callback?.search !== search) {
      this.callback = { search, promise: this.exchange(search) };
    }
    return this.callback.promise;
  }

  private async exchange(search: string): Promise<void> {
    const params = new URLSearchParams(search);
    const expectedState = this.deps.storage.getItem(STATE_KEY);
    const verifier = this.deps.storage.getItem(VERIFIER_KEY);
    // One-time values: remove before anything can fail.
    this.deps.storage.removeItem(STATE_KEY);
    this.deps.storage.removeItem(VERIFIER_KEY);
    this.authorizeUrl = null;

    const error = params.get("error");
    if (error) throw new AuthError(`Sign-in was not completed (${error}).`);
    const code = params.get("code");
    if (!code) throw new AuthError("Sign-in response is missing the authorization code.");
    if (!expectedState || params.get("state") !== expectedState) {
      throw new AuthError("Sign-in response did not match this browser session. Please try again.");
    }
    if (!verifier) throw new AuthError("Sign-in session expired. Please try again.");

    this.tokens = await this.requestTokens(
      new URLSearchParams({
        grant_type: "authorization_code",
        client_id: this.config.clientId,
        code,
        redirect_uri: this.config.redirectUri,
        code_verifier: verifier,
      }),
      null,
    );
  }

  private async requestTokens(body: URLSearchParams, keepRefresh: string | null): Promise<TokenSet> {
    const response = await this.deps.fetch(`${this.config.domain}/oauth2/token`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body,
    });
    let data: TokenResponse = {};
    try {
      data = (await response.json()) as TokenResponse;
    } catch {
      // fall through to the error below
    }
    if (!response.ok || !data.access_token || !data.expires_in) {
      throw new AuthError("Could not complete sign-in. Please try again.");
    }
    return {
      accessToken: data.access_token,
      refreshToken: data.refresh_token ?? keepRefresh,
      expiresAt: this.deps.now() + data.expires_in * 1000,
    };
  }

  /** A valid access token, refreshing first when it is about to expire. Null if signed out. */
  async getAccessToken(): Promise<string | null> {
    if (!this.tokens) return null;
    if (this.tokens.expiresAt - this.deps.now() < REFRESH_MARGIN_MS) {
      await this.refresh();
    }
    return this.tokens?.accessToken ?? null;
  }

  /** Exchange the refresh token for a new access token. False means a new sign-in is needed. */
  refresh(): Promise<boolean> {
    this.refreshing ??= this.doRefresh().finally(() => {
      this.refreshing = null;
    });
    return this.refreshing;
  }

  private async doRefresh(): Promise<boolean> {
    const refreshToken = this.tokens?.refreshToken;
    if (!refreshToken) {
      this.clear();
      return false;
    }
    try {
      this.tokens = await this.requestTokens(
        new URLSearchParams({
          grant_type: "refresh_token",
          client_id: this.config.clientId,
          refresh_token: refreshToken,
        }),
        refreshToken,
      );
      return true;
    } catch {
      this.clear();
      return false;
    }
  }

  clear(): void {
    this.tokens = null;
    this.authorizeUrl = null;
    this.callback = null;
  }

  logoutUrl(): string {
    const params = new URLSearchParams({
      client_id: this.config.clientId,
      logout_uri: this.config.logoutUri,
    });
    return `${this.config.domain}/logout?${params.toString()}`;
  }
}
