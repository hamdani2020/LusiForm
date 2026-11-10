import type { ReactNode } from "react";

import { BrandMark } from "@/components/BrandMark";

interface StatusCardProps {
  title: string;
  body: string;
  /** Shows a polite status instead of an alert. */
  busy?: boolean;
  children?: ReactNode;
}

/** Centred card in the Sign In screen's layout, for in-between and error states. */
export function StatusCard({ title, body, busy = false, children }: StatusCardProps) {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header className="border-b bg-card px-8 py-4">
        <BrandMark />
      </header>
      <main className="flex flex-1 items-center justify-center px-4 py-12">
        <section
          aria-busy={busy}
          className="w-full max-w-[440px] rounded-lg border bg-card p-8 text-center shadow-sm"
        >
          <h1 className="text-lg font-semibold tracking-tight text-navy">{title}</h1>
          <p role={busy ? "status" : "alert"} className="mt-2 text-sm text-muted-foreground">
            {body}
          </p>
          {children ? <div className="mt-6 flex justify-center gap-2">{children}</div> : null}
        </section>
      </main>
      <footer className="border-t bg-card px-8 py-4 text-center text-xs text-muted-foreground">
        Lusiform
      </footer>
    </div>
  );
}
