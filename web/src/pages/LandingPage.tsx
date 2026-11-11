import { Code2, Lock, Share2 } from "lucide-react";

import { BrandMark } from "@/components/BrandMark";
import { Button } from "@/components/ui/button";
import { STAGES } from "@/content/stages";

interface LandingPageProps {
  /** Sends the user to the Cognito hosted login. Undefined when sign-in is not configured. */
  onSignIn?: () => void;
  /** Sign-in problem to show (failed callback, misconfiguration). */
  message?: { title: string; body: string };
}

const FEATURES = [
  {
    icon: Share2,
    title: "One architecture graph",
    body: "The diagram and the Terraform are rendered from the same graph, and a parity check blocks export if they disagree.",
  },
  {
    icon: Lock,
    title: "Nothing applies without approval",
    body: "Sandbox apply runs only from a plan whose hash a named consultant approved. The assistant can't approve, apply, or destroy.",
  },
  {
    icon: Code2,
    title: "Deterministic output",
    body: "The same intake and template version always produce the same Terraform.",
  },
] as const;

/**
 * Public, signed-out page (Stitch "Lusiform - Public Landing Page"). Its only action is
 * "Sign in", which goes to the Cognito hosted login. Access is by invitation, so there is
 * no sign-up, and the page makes no pricing, uptime, or compliance claim.
 */
export function LandingPage({ onSignIn, message }: LandingPageProps) {
  const signIn = (size: "default" | "lg") => (
    <Button size={size} onClick={onSignIn} disabled={!onSignIn}>
      Sign in
    </Button>
  );

  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <header className="sticky top-0 z-30 border-b bg-card">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-6">
          <BrandMark />
          {signIn("default")}
        </div>
      </header>

      <main className="flex-1">
        <section className="mx-auto max-w-7xl px-6 pt-16 pb-20 lg:pt-24 lg:pb-28">
          <div className="grid grid-cols-1 items-center gap-12 lg:grid-cols-12 lg:gap-14">
            <div className="flex flex-col items-start lg:col-span-7 lg:pr-6">
              <h1 className="mb-6 text-3xl leading-[1.15] font-bold tracking-tight text-navy sm:text-4xl lg:text-5xl">
                From requirements to a validated Terraform project
              </h1>
              <p className="mb-8 max-w-2xl text-base leading-relaxed text-muted-foreground sm:text-lg">
                Lusiform helps AWS Partner consultants take a startup customer from a requirements
                conversation to a reviewable architecture diagram, a cost estimate, and a validated
                Terraform project, then deploy it to your partner sandbox account after a named
                consultant approves the exact plan.
              </p>

              {message ? (
                <div
                  role="alert"
                  className="mb-6 w-full max-w-2xl rounded-lg border border-destructive/30 bg-destructive/5 p-4"
                >
                  <p className="text-sm font-semibold text-destructive">{message.title}</p>
                  <p className="mt-1 text-sm text-muted-foreground">{message.body}</p>
                </div>
              ) : null}

              <div className="flex flex-col items-start gap-2.5">
                {signIn("lg")}
                <span className="text-xs text-muted-foreground">
                  Access is by invitation from your partner admin.
                </span>
              </div>
            </div>

            <div className="w-full lg:col-span-5" aria-hidden="true">
              <ArchitectureCard />
            </div>
          </div>
        </section>

        <section aria-labelledby="stages-heading" className="border-t bg-card py-16 lg:py-20">
          <div className="mx-auto max-w-7xl px-6">
            <h2 id="stages-heading" className="mb-10 text-2xl font-bold tracking-tight text-navy">
              How a project moves
            </h2>
            <ol className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
              {STAGES.map((stage, i) => (
                <li key={stage.name} className="rounded-lg border bg-background/40 p-4">
                  <div className="mb-2 flex items-center gap-2">
                    <span className="flex size-6 items-center justify-center rounded bg-navy font-mono text-xs font-medium text-white">
                      {i + 1}
                    </span>
                    <span className="text-sm font-semibold text-navy">{stage.name}</span>
                  </div>
                  <p
                    className={
                      stage.name === "Validation"
                        ? "font-mono text-xs leading-relaxed text-muted-foreground"
                        : "text-xs leading-relaxed text-muted-foreground"
                    }
                  >
                    {stage.description}
                  </p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section className="mx-auto max-w-7xl px-6 py-16 lg:py-20">
          <div className="grid grid-cols-1 gap-6 md:grid-cols-3 lg:gap-8">
            {FEATURES.map(({ icon: Icon, title, body }) => (
              <div key={title} className="rounded-lg border bg-card p-6 shadow-sm">
                <div className="mb-4 flex size-8 items-center justify-center rounded-md border border-mint bg-accent text-primary">
                  <Icon className="size-4" aria-hidden="true" />
                </div>
                <h3 className="mb-2.5 text-lg font-bold text-navy">{title}</h3>
                <p className="text-sm leading-relaxed text-muted-foreground">{body}</p>
              </div>
            ))}
          </div>
        </section>
      </main>

      <footer className="border-t bg-card py-6">
        <p className="text-center text-xs font-medium text-muted-foreground">Lusiform</p>
      </footer>
    </div>
  );
}

/** Decorative: the startup reference architecture as labelled boxes. */
function ArchitectureCard() {
  const box = "rounded border bg-card p-3 text-center text-xs font-medium text-navy";
  return (
    <div className="rounded-lg border bg-card p-6 shadow-sm">
      <div className="mb-5 border-b pb-4 text-xs font-semibold text-navy">
        Startup reference architecture
      </div>
      <div className="rounded-lg border bg-background/60 p-5">
        <p className="mb-4 font-mono text-xs font-semibold text-navy">VPC</p>
        <div className={`${box} mb-6`}>ECS Fargate service</div>
        <div className="flex justify-center">
          <div className="h-6 w-px bg-border" />
        </div>
        <div className="relative pt-3">
          <div className="absolute top-0 right-1/4 left-1/4 h-px bg-border" />
          <div className="absolute top-0 left-1/4 h-3 w-px bg-border" />
          <div className="absolute top-0 right-1/4 h-3 w-px bg-border" />
          <div className="grid grid-cols-2 gap-3 pt-1">
            <div className={box}>RDS PostgreSQL</div>
            <div className={box}>CloudWatch logs</div>
          </div>
        </div>
      </div>
    </div>
  );
}
