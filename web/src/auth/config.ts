/** Cognito hosted-login settings, read from build-time env. None of these are secrets. */

export interface AuthConfig {
  /** Hosted UI domain, e.g. https://lusiform-dev.auth.us-east-1.amazoncognito.com */
  domain: string;
  /** App client id of a PUBLIC client (no client secret; PKCE is used). */
  clientId: string;
  redirectUri: string;
  logoutUri: string;
  scopes: string;
}

type EnvLike = Record<string, string | undefined>;

export const CALLBACK_PATH = "/auth/callback";

/** Returns null when sign-in is not configured, so the app can say so instead of redirecting nowhere. */
export function loadAuthConfig(
  env: EnvLike = import.meta.env,
  origin: string = window.location.origin,
): AuthConfig | null {
  const rawDomain = env.VITE_COGNITO_DOMAIN?.trim();
  const clientId = env.VITE_COGNITO_CLIENT_ID?.trim();
  if (!rawDomain || !clientId) return null;

  let domain: URL;
  try {
    domain = new URL(rawDomain.startsWith("http") ? rawDomain : `https://${rawDomain}`);
  } catch {
    return null;
  }
  if (domain.protocol !== "https:") return null; // tokens never travel over plain http

  return {
    domain: domain.origin,
    clientId,
    redirectUri: `${origin}${CALLBACK_PATH}`,
    logoutUri: `${origin}/`,
    scopes: "openid email",
  };
}
