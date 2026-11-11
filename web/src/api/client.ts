import type { AuthClient } from "@/auth/client";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface Api {
  get<T>(path: string): Promise<T>;
}

/**
 * Calls the Lusiform API with `Authorization: Bearer <access token>`.
 * On a 401 it refreshes the token once and retries; a second 401 means the session is over.
 */
export function createApi(
  auth: AuthClient,
  fetchImpl: typeof fetch = (...args) => globalThis.fetch(...args),
  baseUrl = "",
): Api {
  async function send(path: string): Promise<Response> {
    const token = await auth.getAccessToken();
    if (!token) throw new ApiError(401, "Not signed in");
    return fetchImpl(`${baseUrl}${path}`, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
    });
  }

  return {
    async get<T>(path: string): Promise<T> {
      let response = await send(path);
      if (response.status === 401 && (await auth.refresh())) {
        response = await send(path);
      }
      if (response.status === 401) {
        auth.clear();
        throw new ApiError(401, "Your session has ended");
      }
      if (!response.ok) {
        throw new ApiError(response.status, `Request failed (${response.status})`);
      }
      return (await response.json()) as T;
    },
  };
}
