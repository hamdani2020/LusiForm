import type { Role } from "@/api/me";

export interface NavItem {
  label: string;
}

/**
 * Admin navigation by role (agent-and-admin spec). The pages arrive with that spec, so
 * the entries are shown as unavailable rather than as links that go nowhere.
 */
const ADMIN_NAV: Record<"partner_admin" | "platform_operator", NavItem[]> = {
  partner_admin: [
    { label: "Users & Roles" },
    { label: "Sandbox Accounts" },
    { label: "Default Assumptions" },
  ],
  platform_operator: [
    { label: "Partners" },
    { label: "Template Versions" },
    { label: "Default Assumptions" },
    { label: "Audit Log" },
  ],
};

export function adminNavFor(roles: Role[]): NavItem[] {
  const seen = new Set<string>();
  const items: NavItem[] = [];
  for (const role of ["platform_operator", "partner_admin"] as const) {
    if (!roles.includes(role)) continue;
    for (const item of ADMIN_NAV[role]) {
      if (!seen.has(item.label)) {
        seen.add(item.label);
        items.push(item);
      }
    }
  }
  return items;
}
