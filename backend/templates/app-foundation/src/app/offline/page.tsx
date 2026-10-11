// Shown by the service worker when the application cannot be reached: the
// one page the installed app keeps, so "no network" is said rather than a
// browser error. Static — it imports nothing that needs a request.
export const dynamic = "force-static";

export default function OfflinePage() {
  return (
    <main className="grid min-h-screen place-items-center bg-background p-6 text-foreground">
      <div className="max-w-sm text-center">
        <h1 className="text-2xl font-semibold tracking-tight">You&apos;re offline</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          This page needs a connection. What you were looking at will be back once you are online again.
        </p>
        <a href="./" className="mt-6 inline-flex h-10 items-center justify-center rounded-md bg-primary px-5 text-sm font-medium text-primary-foreground">
          Try again
        </a>
      </div>
    </main>
  );
}
