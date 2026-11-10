import { useState, type FormEvent } from "react";
import { ArrowLeft, Layers } from "lucide-react";

import { Button } from "@/components/ui/button";

interface SignInPreviewProps {
  onBack: () => void;
}

/**
 * DEV-ONLY design preview of the Stitch "Sign In" screen (5e604a130e1b48d5aa941a4e5e2ae5b5).
 *
 * The real sign-in form is Cognito's hosted login, themed to match this design. Lusiform
 * never handles passwords. This preview exists so the design can be reviewed before a
 * Cognito pool exists: the fields have no `name`, the form has no action, and submitting
 * only shows a note. Nothing typed here is stored or sent anywhere. It is shown only when
 * Cognito is not configured and the app is a development build.
 */
export function SignInPreview({ onBack }: SignInPreviewProps) {
  const [submitted, setSubmitted] = useState(false);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    event.currentTarget.reset(); // drop whatever was typed
    setSubmitted(true);
  }

  const input =
    "h-10 w-full rounded-md border bg-background px-3.5 text-xs text-navy placeholder:text-muted-foreground/70 transition-colors focus:border-primary focus:bg-card focus:outline-none";

  return (
    <div className="flex min-h-screen flex-col justify-between bg-background text-navy">
      <div
        role="note"
        className="border-b border-warning/30 bg-warning/10 px-8 py-2 text-center text-xs text-warning"
      >
        Design preview. Cognito is not configured, so this form signs no one in and sends
        nothing. The real sign-in page is Cognito&apos;s hosted login, styled to match.
      </div>

      <header className="flex w-full items-center justify-between border-b bg-card px-8 py-4">
        <div className="flex items-center gap-2.5">
          <span
            aria-hidden="true"
            className="flex size-7 items-center justify-center rounded-md bg-navy font-mono text-xs font-semibold tracking-wider text-white"
          >
            L
          </span>
          <span className="text-base font-semibold tracking-tight">Lusiform</span>
        </div>
        <Button variant="ghost" size="sm" onClick={onBack}>
          <ArrowLeft className="size-4" aria-hidden="true" />
          Back
        </Button>
      </header>

      <main className="flex flex-1 flex-col items-center justify-center px-4 py-12">
        <div className="w-full max-w-[440px]">
          <div className="mb-8 text-center">
            <div className="mb-3 inline-flex items-center justify-center gap-3">
              <span
                aria-hidden="true"
                className="flex size-10 items-center justify-center rounded-md bg-navy text-teal-400 shadow-sm"
              >
                <Layers className="size-6" />
              </span>
              <span className="text-3xl font-bold tracking-tight">Lusiform</span>
            </div>
            <p className="text-sm leading-relaxed text-muted-foreground">
              Requirements to deployed infrastructure for AWS partners
            </p>
          </div>

          <div className="rounded-lg border bg-card p-8 shadow-sm">
            <div className="mb-6">
              <h1 className="text-lg font-semibold tracking-tight">Sign In</h1>
              <p className="mt-1 text-xs text-muted-foreground">
                Enter your credentials to access your account.
              </p>
            </div>

            <form className="space-y-4" onSubmit={onSubmit} noValidate>
              <div>
                <label htmlFor="preview-email" className="mb-1.5 block text-xs font-medium">
                  Email address
                </label>
                <input
                  id="preview-email"
                  type="email"
                  autoComplete="off"
                  placeholder="name@partner.com"
                  className={input}
                />
              </div>
              <div>
                <div className="mb-1.5 flex items-center justify-between">
                  <label htmlFor="preview-password" className="block text-xs font-medium">
                    Password
                  </label>
                  <span className="text-xs font-medium text-muted-foreground">
                    Forgot password?
                  </span>
                </div>
                <input
                  id="preview-password"
                  type="password"
                  autoComplete="off"
                  placeholder="••••••••••••"
                  className={input}
                />
              </div>
              <Button type="submit" size="lg" className="mt-2 w-full text-sm">
                Sign in
              </Button>
            </form>

            {submitted ? (
              <p role="status" className="mt-4 text-center text-xs text-muted-foreground">
                Preview only: nothing was sent. Configure Cognito to sign in for real.
              </p>
            ) : null}
          </div>

          <p className="mt-6 text-center text-xs text-muted-foreground">
            Access is by invitation from your partner admin.
          </p>
        </div>
      </main>

      <footer className="w-full border-t bg-card px-8 py-4 text-center font-mono text-xs text-muted-foreground/80">
        Lusiform
      </footer>
    </div>
  );
}
