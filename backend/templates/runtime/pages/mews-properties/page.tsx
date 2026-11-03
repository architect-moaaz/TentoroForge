/**
 * The hotels this application reaches in Mews: add a property with its
 * enterprise id and access token, check it connects, change or remove it.
 * The administrator's page (the API answers anyone else 403); an application
 * with no Mews integration says so. Forge runtime — do not edit by hand.
 */
import { cookies, headers } from "next/headers";
import { MewsPropertiesPanel } from "./MewsPropertiesPanel";

export const dynamic = "force-dynamic";

async function read(path: string): Promise<{ status: number; body: any }> {
  const cookieHeader = (await cookies()).getAll().map((c) => `${c.name}=${c.value}`).join("; ");
  const host = (await headers()).get("host") || "localhost:3000";
  const proto = (await headers()).get("x-forwarded-proto") || "http";
  try {
    const res = await fetch(`${proto}://${host}${path}`, { headers: { cookie: cookieHeader }, cache: "no-store" });
    return { status: res.status, body: await res.json().catch(() => ({})) };
  } catch (err) {
    return { status: 0, body: { error: String(err) } };
  }
}

export default async function MewsPropertiesPage() {
  const res = await read("/api/mews/properties");
  return (
    <div className="p-6 max-w-4xl mx-auto">
      <h1 className="text-2xl font-semibold mb-1">Mews properties</h1>
      <p className="text-sm text-muted-foreground mb-6">
        The hotels this application reads and writes in Mews. Each property&apos;s access token is stored encrypted and is
        never shown again; the integration&apos;s client token is set once for the organisation.
      </p>
      {res.status === 200
        ? <MewsPropertiesPanel properties={res.body?.properties ?? []} />
        : <p className="text-muted-foreground">{res.body?.error ?? "The properties could not be read."}</p>}
    </div>
  );
}
