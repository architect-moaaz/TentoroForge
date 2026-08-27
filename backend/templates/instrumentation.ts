export async function register() {
  if (process.env.NEXT_RUNTIME === 'nodejs') {
    setInterval(async () => {
      try {
        await fetch(
          `${process.env.NEXTAUTH_URL || 'http://localhost:3000'}/api/workflows/cron`,
          { method: 'POST' },
        );
      } catch {
        // Silently ignore — server may not be ready yet
      }
    }, 15_000);
  }
}
