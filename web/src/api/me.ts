import type { Api } from "./client";

export type Role = "partner_admin" | "consultant" | "platform_operator";

/** Response of GET /api/me. Roles come from the server, never from the token. */
export interface Me {
  user_id: string;
  partner_id: string;
  partner_name: string;
  email: string;
  display_name: string | null;
  roles: Role[];
}

export function fetchMe(api: Api): Promise<Me> {
  return api.get<Me>("/api/me");
}

export const ROLE_LABELS: Record<Role, string> = {
  platform_operator: "Platform operator",
  partner_admin: "Partner admin",
  consultant: "Consultant",
};

/** Highest role first, for display. */
export function roleLabel(roles: Role[]): string {
  const order: Role[] = ["platform_operator", "partner_admin", "consultant"];
  const held = order.filter((r) => roles.includes(r));
  return held.map((r) => ROLE_LABELS[r]).join(", ") || "No role";
}

export function isAdmin(roles: Role[]): boolean {
  return roles.includes("partner_admin") || roles.includes("platform_operator");
}
