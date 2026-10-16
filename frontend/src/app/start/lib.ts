/**
 * The first minute of an account, as data: what kinds of account there are,
 * what each role in an organisation may do (said in one line, where the
 * person chooses it), how typed emails become a list, and how a name becomes
 * the slug the person sees change as they type.
 */
import { slugFromName } from "@/lib/brand";

export type AccountType = "personal" | "business" | "joining";

export const ACCOUNT_TYPES: ReadonlyArray<{ value: AccountType; title: string; hint: string }> = [
  { value: "personal", title: "Personal", hint: "I'm building apps for myself or a side project." },
  { value: "business", title: "Business", hint: "I'm building apps for a company, in its brand." },
  { value: "joining", title: "I'm joining an existing team", hint: "Somebody invited me to their organisation." },
];

export type MemberRole = "owner" | "admin" | "member";

/** What each role may do — the same answer the API gives when it refuses. */
export const ROLES: ReadonlyArray<{ value: MemberRole; title: string; hint: string }> = [
  { value: "admin", title: "Admin", hint: "Invite and manage members, people and settings; build and publish apps." },
  { value: "member", title: "Member", hint: "Build and use the organisation's apps; cannot manage members or settings." },
  { value: "owner", title: "Owner", hint: "Everything an admin can, and the organisation itself: its name, address and removal." },
];

/** Emails typed in one box: commas, spaces or new lines between them, each once, lower-cased. */
export function parseEmails(text: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of text.split(/[\s,;]+/)) {
    const e = raw.trim().toLowerCase();
    if (!e || seen.has(e)) continue;
    seen.add(e);
    out.push(e);
  }
  return out;
}

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** The addresses that are not addresses, to point at before anything is sent. */
export function badEmails(list: string[]): string[] {
  return list.filter((e) => !EMAIL.test(e));
}

/** The slug the person sees change as they type the name; "" when the name has no letters or digits. */
export function slugPreview(name: string): string {
  return /[a-z0-9]/i.test(name) ? slugFromName(name) : "";
}

const SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

/** A slug a person edited by hand: lower-case words and digits joined by single hyphens, 2 to 100 long. */
export function slugProblem(slug: string): string {
  if (!slug) return "Give the organisation a web address.";
  if (slug.length < 2) return "The address needs at least two characters.";
  if (slug.length > 100) return "The address is too long.";
  if (!SLUG.test(slug)) return "Use lower-case letters, digits and single hyphens.";
  return "";
}
