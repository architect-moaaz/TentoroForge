/** The Drafts Room's shapes, as `routers/drafts_room.py` returns them. */

export type FileMeta = {
  id: string;
  name: string;
  media_type: string;
  origin: "upload" | "screenshot" | "research";
  job?: string;
  caption: string;
  source: string;
  size: number;
  at: number;
};

export type ChatEntry = {
  role: "user" | "assistant";
  text: string;
  files?: string[];
  steps?: string[];
  at?: number;
  handoff?: { project_id: string; app_name: string };
};

type Named = { name: string };

export type Board = {
  status: "exploring" | "agreed";
  product: { name?: string; pitch?: string; audience?: string; platforms?: string[]; kind?: string };
  look: {
    mood?: string;
    palette?: { name?: string; hex?: string }[];
    fonts?: string[];
    layout?: string;
    avoid?: string;
  };
  references: (Named & { url?: string; why?: string; took?: string[] })[];
  roles: (Named & { does?: string })[];
  features: (Named & { detail?: string; priority?: "must" | "should" | "later"; from?: string })[];
  screens: (Named & { role?: string; purpose?: string; shows?: string[]; actions?: string[]; device?: "phone" | "desktop"; like?: string })[];
  flows: (Named & { role?: string; goal?: string; steps: { screen: string; does?: string }[] })[];
  entities: (Named & { fields?: { name: string; type?: string }[]; links?: { to: string; kind?: "one" | "many" }[] })[];
  decisions: { text: string }[];
  questions: { text: string; options?: string[] }[];
};

export type Dossier = {
  product: { name?: string; what?: string; audience?: string; platforms?: string[]; business?: string };
  look: Board["look"] & { density?: string; signature?: string[] };
  surfaces: (Named & { url?: string; kind?: string; reachable?: boolean; note?: string })[];
  roles: Board["roles"];
  features: (Named & { detail?: string; area?: string; where?: string; source?: string })[];
  screens: (Named & { surface?: string; url?: string; purpose?: string; shows?: string[]; actions?: string[]; shot?: string })[];
  flows: Board["flows"];
  entities: Board["entities"];
  rules: { text: string; source?: string }[];
  voices: { text: string; kind?: "love" | "hate" | "wish"; source?: string }[];
  gaps: { text: string }[];
};

export type Standing = "observed" | "derived" | "inferred" | "unknown";
export type EvidenceKind = "record" | "field" | "enum" | "action" | "screen" | "flow" | "rule" | "role" | "voice" | "gap";

/** One fact a study found, with how well it is known and where it came from. */
export type EvidenceItem = {
  id: string;
  reference: string;
  kind: EvidenceKind;
  text: string;
  data?: unknown;
  standing: Standing;
  sources: { type: string; ref?: string; url?: string }[];
  at: number;
};

export type Study = {
  id: string;
  reference: string;
  focus: string;
  /** `surface` is the Researcher reading pages; `deep` is the browser recording calls (`web`) or the person's own recording (`har`). */
  kind?: "surface" | "deep";
  source?: "web" | "har" | "";
  reference_id?: string;
  capture?: { pages: number; calls: number; hosts: string[]; stopped_on: string | null };
  /** Counts per standing (the items themselves come from the evidence route). */
  evidence?: Record<Standing, number>;
  evidence_total?: number;
  status: "running" | "done" | "failed" | "stopped";
  stage: string;
  started: number;
  finished: number | null;
  steps: { at: number; text: string }[];
  surfaces: { name: string; url?: string; kind?: string; look_for?: string }[];
  dossier: Dossier;
  summary: string;
  files: FileMeta[];
  error: string | null;
  read: boolean;
};

/** One screen of the board, drawn as a page in the company's brand. */
export type Drawing = {
  id: string;
  screen: string;
  status: "drawing" | "done" | "failed";
  viewport: "phone" | "desktop";
  html: boolean;
  png: boolean;
  caption: string;
  brand_source: "company" | "board" | "none";
  like?: string;
  error?: string | null;
  at: number;
  /** The screen, the brand or the product changed since it was drawn. */
  stale?: boolean;
  /** "board", or "draft:<id>" for a draft's screens. */
  scope?: string;
};

/** What the person pointed at, and the studies made of it. */
export type Reference = {
  id: string;
  name: string;
  url: string;
  added_by: string;
  at: number;
  allowed: string[];
  studies: { surface?: string; deep?: string; har?: string };
  har: null | { calls: number; at: number; study: string };
};

type Lined = { evidence: string[] };
/** One feature of a reference in Forge's terms, every line resting on evidence. */
export type Card = {
  id: string;
  reference: string;
  feature: string;
  summary: string;
  records: (Lined & { name: string; fields: (Lined & { name: string; type?: string })[] })[];
  steps: (Lined & { does: string; screen?: string })[];
  screens: (Lined & { name: string; purpose?: string; shows?: string[]; actions?: string[]; device?: "phone" | "desktop" })[];
  rules: (Lined & { text: string })[];
  roles: (Lined & { name: string; does?: string })[];
  needs: string[];
  unknowns: string[];
  standing: Record<Standing, number>;
  at: number;
};

export type Estimate = {
  units: number; measured_on: string;
  cost: { low: number; high: number }; minutes: { low: number; high: number }; fixes: { low: number; high: number };
};

/** A candidate app as it stands (its latest version), with its version list. */
export type Draft = {
  id: string;
  version: number;
  title: string;
  pitch: string;
  roles: { name: string; does?: string }[];
  features: { name: string; detail?: string; priority?: "must" | "should" | "later"; from_card?: string }[];
  screens: { name: string; role?: string; purpose?: string; shows?: string[]; actions?: string[]; device?: "phone" | "desktop" }[];
  records: { name: string; fields?: { name: string; type?: string }[]; links?: { to: string; kind?: string }[] }[];
  rules?: string[];
  flows?: { name: string; role?: string; goal?: string; steps: { screen: string; does?: string }[] }[];
  left_out?: string[];
  assumed?: string[];
  needs: string[];
  estimate: Estimate;
  cannot_yet: { kind: string; status: "proven" | "unproven" | "not_yet"; what: string; proof: string }[];
  notes: { at: number; on: string; text: string }[];
  changed: string;
  created: number;
  at: number;
  versions?: { version: number; at: number; changed: string }[];
};

export type Session = {
  id: string;
  org_id: string;
  title: string;
  chat: ChatEntry[];
  board: Board;
  files: FileMeta[];
  handoff: null | { project_id: string; app_name: string; description?: string; document: string; opening: string;
                    build?: "started" | "not_started"; error?: string; at: number };
  usage?: Record<string, number>;
  busy?: boolean;
  research?: Study[];
  drawings?: Drawing[];
  brand?: { source: "company" | "board" | "none"; company?: string };
  references?: Reference[];
  cards?: Card[];
  drafts?: Draft[];
  chosen_draft?: { id: string; version: number; title: string; at: number } | null;
};

export type SessionRow = {
  id: string;
  title: string;
  updated_at: number;
  agreed: boolean;
  messages: number;
  project_id?: string | null;
};
