import { cn } from "@/lib/utils";

/** Navy "L" tile and wordmark, as on the Sign In and Public Landing Page designs. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <span className={cn("flex items-center gap-2.5 select-none", className)}>
      <span
        aria-hidden="true"
        className="flex size-8 items-center justify-center rounded-md bg-navy font-mono text-sm font-semibold text-white shadow-sm"
      >
        L
      </span>
      <span className="text-lg font-bold tracking-tight text-navy">Lusiform</span>
    </span>
  );
}
