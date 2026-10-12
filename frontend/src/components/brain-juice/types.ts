/** Brain Juice's shapes, as `routers/brain_juice.py` returns them. */

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
  screens: (Named & { role?: string; purpose?: string; shows?: string[]; actions?: string[]; like?: string })[];
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

export type Study = {
  id: string;
  reference: string;
  focus: string;
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

export type Session = {
  id: string;
  org_id: string;
  title: string;
  chat: ChatEntry[];
  board: Board;
  files: FileMeta[];
  handoff: null | { project_id: string; app_name: string; document: string; opening: string; at: number };
  usage?: Record<string, number>;
  busy?: boolean;
  research?: Study[];
};

export type SessionRow = {
  id: string;
  title: string;
  updated_at: number;
  agreed: boolean;
  messages: number;
  project_id?: string | null;
};
