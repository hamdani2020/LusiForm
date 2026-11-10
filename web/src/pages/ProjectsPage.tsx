import { CheckCircle2, FolderOpen, Plus, ShieldCheck, Wallet } from "lucide-react";

import { Button } from "@/components/ui/button";
import { STAGES } from "@/content/stages";

const HIGHLIGHTS = [
  {
    icon: CheckCircle2,
    title: "Validated Terraform",
    body: "fmt, validate, tflint and Checkov run on every generation",
  },
  {
    icon: Wallet,
    title: "Cost estimate",
    body: "Prices from the AWS Pricing API with editable assumptions",
  },
  {
    icon: ShieldCheck,
    title: "Reviewed deployment",
    body: "Sandbox apply only after a named approval of the exact plan",
  },
] as const;

/**
 * Projects landing (Stitch "Projects (Empty State)"). Listing and creating projects arrive
 * with the intake spec, so "New project" is shown but not yet available.
 */
export function ProjectsPage() {
  const newProject = (
    <Button disabled title="Available in a later release">
      <Plus className="size-4" aria-hidden="true" />
      New project
    </Button>
  );

  return (
    <>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight text-navy">Projects</h1>
        {newProject}
      </div>

      <section
        aria-label="No projects"
        className="mx-auto my-2 flex w-full max-w-3xl flex-col items-center rounded-lg border bg-card p-12 text-center"
      >
        <div className="mb-4 flex size-14 items-center justify-center rounded-lg border bg-background text-primary">
          <FolderOpen className="size-7" aria-hidden="true" />
        </div>
        <h2 className="mb-2 text-xl font-semibold text-navy">No projects yet</h2>
        <p className="mb-6 max-w-lg text-sm leading-relaxed text-muted-foreground">
          The first step is intake. Answer questions about the workload to generate a validated
          diagram, cost estimate, and Terraform project.
        </p>
        {newProject}
      </section>

      <section aria-labelledby="stages-heading">
        <h2
          id="stages-heading"
          className="mb-3 px-1 text-xs font-semibold tracking-wider text-muted-foreground uppercase"
        >
          How a project moves
        </h2>
        <ol className="grid grid-cols-2 gap-2.5 md:grid-cols-4 xl:grid-cols-8">
          {STAGES.map((stage, i) => (
            <li key={stage.name} className="flex min-h-[92px] flex-col rounded-md border bg-card p-3">
              <div className="mb-1.5 flex items-center gap-1.5">
                <span className="flex size-4 items-center justify-center rounded-full bg-secondary font-mono text-[11px] font-medium text-muted-foreground">
                  {i + 1}
                </span>
                <span className="text-xs font-semibold text-navy">{stage.name}</span>
              </div>
              <p className="text-[11px] leading-snug text-muted-foreground">{stage.description}</p>
            </li>
          ))}
        </ol>
      </section>

      <div className="mb-8 grid grid-cols-1 gap-6 md:grid-cols-3">
        {HIGHLIGHTS.map(({ icon: Icon, title, body }) => (
          <div key={title} className="flex flex-col rounded-lg border bg-card p-5">
            <div className="mb-2 flex items-center gap-2">
              <Icon className="size-5 text-primary" aria-hidden="true" />
              <h3 className="text-sm font-semibold text-navy">{title}</h3>
            </div>
            <p className="text-xs leading-relaxed text-muted-foreground">{body}</p>
          </div>
        ))}
      </div>
    </>
  );
}
