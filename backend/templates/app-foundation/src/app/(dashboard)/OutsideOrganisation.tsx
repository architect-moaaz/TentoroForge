/**
 * Opened at an organisation's own address by someone who does not belong to
 * it: said plainly, with the addresses of the organisations they do belong
 * to. Nothing of that organisation is shown. Forge runtime — do not remove.
 */
import * as tenancy from "@/lib/tenancy";

export async function OutsideOrganisation({ userId, slug }: { userId: string; slug: string }) {
  let mine: Array<{ name: string; address: string }> = [];
  try {
    for (const m of await tenancy.membershipsOf(userId)) {
      const s = await tenancy.slugOf(m.orgId);
      if (s) mine.push({ name: m.orgName ?? s, address: tenancy.addressOf(s) });
    }
  } catch { mine = []; }
  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-4 p-6">
      <h1 className="text-2xl font-semibold">You are not a member here</h1>
      <p className="text-muted-foreground">
        {slug}.{tenancy.orgDomain()} belongs to an organisation you are not part of. Ask its admin to invite you.
      </p>
      {mine.length > 0 && (
        <div className="space-y-2">
          <p className="text-sm font-medium">Your organisations</p>
          <ul className="space-y-1">
            {mine.map((m) => (
              <li key={m.address}><a className="text-primary underline" href={m.address}>{m.name}</a></li>
            ))}
          </ul>
        </div>
      )}
      <a className="text-sm text-muted-foreground underline" href="/api/auth/signout">Sign out</a>
    </main>
  );
}
