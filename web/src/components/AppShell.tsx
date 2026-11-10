import type { ReactNode } from "react";
import { FolderOpen, LogOut } from "lucide-react";

import { isAdmin, roleLabel, type Me } from "@/api/me";
import { BrandMark } from "@/components/BrandMark";

import { adminNavFor } from "./adminNav";

interface AppShellProps {
  me: Me;
  onSignOut: () => void;
  /** Breadcrumb for the current page, shown after the partner name. */
  page: string;
  children: ReactNode;
}

function initials(name: string): string {
  const parts = name.replace(/@.*/, "").split(/[\s._-]+/).filter(Boolean);
  return (parts.length > 1 ? parts[0][0] + parts[1][0] : name.slice(0, 2)).toUpperCase();
}

/**
 * Authenticated layout (Stitch "Projects (Empty State)"): sidebar with the brand, Projects
 * navigation, role-gated admin entries and the signed-in user; top bar with
 * "<partner> / <page>" and the user's name and role. A user has one partner, so there is
 * no workspace picker.
 */
export function AppShell({ me, onSignOut, page, children }: AppShellProps) {
  const name = me.display_name || me.email;
  const role = roleLabel(me.roles);
  const adminItems = isAdmin(me.roles) ? adminNavFor(me.roles) : [];

  return (
    <div className="min-h-screen bg-background text-foreground">
      <aside className="fixed inset-y-0 left-0 z-30 flex w-60 flex-col justify-between border-r bg-background p-4">
        <div className="flex flex-col gap-6">
          <BrandMark className="px-2 pt-1" />

          <nav aria-label="Main" className="flex flex-col gap-6">
            <ul className="flex flex-col gap-1">
              <li>
                <a
                  href="/"
                  aria-current="page"
                  className="flex items-center gap-3 rounded-md bg-accent px-3 py-2 text-sm font-medium text-primary"
                >
                  <FolderOpen className="size-4" aria-hidden="true" />
                  Projects
                </a>
              </li>
            </ul>

            {adminItems.length > 0 ? (
              <div>
                <h2 className="px-3 pb-2 text-xs font-semibold tracking-wider text-muted-foreground uppercase">
                  Administration
                </h2>
                <ul className="flex flex-col gap-1" aria-label="Administration">
                  {adminItems.map((item) => (
                    <li key={item.label}>
                      <button
                        type="button"
                        disabled
                        title="Available in a later release"
                        className="flex w-full items-center rounded-md px-3 py-2 text-left text-sm text-muted-foreground disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        {item.label}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </nav>
        </div>

        <div className="flex items-center gap-3 border-t px-2 pt-4">
          <span
            aria-hidden="true"
            className="flex size-8 shrink-0 items-center justify-center rounded-full bg-secondary text-xs font-medium text-navy"
          >
            {initials(name)}
          </span>
          <div className="flex min-w-0 flex-1 flex-col">
            <span className="truncate text-xs font-medium text-navy" data-testid="user-name">
              {name}
            </span>
            <span className="truncate text-[11px] text-muted-foreground" data-testid="user-role">
              {role}
            </span>
          </div>
          <button
            type="button"
            onClick={onSignOut}
            aria-label="Sign out"
            title="Sign out"
            className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-secondary hover:text-navy focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          >
            <LogOut className="size-4" aria-hidden="true" />
          </button>
        </div>
      </aside>

      <header className="fixed top-0 right-0 left-60 z-20 flex h-14 items-center justify-between border-b bg-card px-6">
        <nav aria-label="Breadcrumb">
          <ol className="flex items-center gap-2.5 text-xs">
            <li className="font-medium text-muted-foreground" data-testid="partner-name">
              {me.partner_name}
            </li>
            <li aria-hidden="true" className="text-border">
              /
            </li>
            <li aria-current="page" className="font-medium text-navy">
              {page}
            </li>
          </ol>
        </nav>
        <div className="flex items-center gap-2.5">
          <span
            aria-hidden="true"
            className="flex size-7 items-center justify-center rounded-full bg-mint text-xs font-semibold text-navy"
          >
            {initials(name)}
          </span>
          <span className="text-xs font-medium text-navy">{name}</span>
          <span className="rounded bg-secondary px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
            {role}
          </span>
        </div>
      </header>

      <main className="ml-60 flex min-h-screen flex-col gap-8 p-8 pt-22">{children}</main>
    </div>
  );
}
