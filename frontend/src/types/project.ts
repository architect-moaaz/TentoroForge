export interface Project {
  id: string;
  short_id: string;
  org_id: string;
  name: string;
  description: string | null;
  owner_id: string;
  status: "draft" | "generating" | "ready" | "error" | "archived";
  preview_port: number | null;
  db_port: number | null;
  created_at: string;
  updated_at: string;
}

export interface ChatMessage {
  id: string;
  project_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  message_type: "chat" | "plan" | "discovery" | "generation" | "error" | "verify_result";
  metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface AgentJob {
  id: string;
  project_id: string;
  agent_type: string;
  status: "pending" | "running" | "completed" | "failed";
  instruction: string | null;
  result: Record<string, unknown> | null;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  created_at: string;
}

export interface Version {
  id: string;
  project_id: string;
  commit_hash: string | null;
  message: string;
  agent_job_id: string | null;
  files_changed: Record<string, unknown> | null;
  created_at: string;
}

export interface SSEEvent {
  event: string;
  data: Record<string, unknown>;
}
