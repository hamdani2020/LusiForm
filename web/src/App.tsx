import { Button } from "@/components/ui/button";

export default function App() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 p-8">
      <h1 className="text-3xl font-semibold">Lusiform</h1>
      <p className="text-muted-foreground">
        From requirements conversation to a validated Terraform project.
      </p>
      <Button>Get started</Button>
    </main>
  );
}
