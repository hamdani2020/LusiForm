import { createContext, useContext } from "react";

import type { Api } from "@/api/client";

export interface AuthContextValue {
  api: Api;
  signOut: () => void;
  /** Start a fresh sign-in (used when the session has ended). */
  signIn: () => void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
