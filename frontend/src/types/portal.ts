export interface PortalApp {
  id: string;
  name: string;
  description: string | null;
  status: string;
  icon?: string;
  preview_port: number | null;
  badges: PortalAppBadges;
}

export interface PortalAppBadges {
  pending_tasks: number;
  alerts: number;
  new_items: number;
}

export interface PortalTask {
  id: string;
  app_id: string;
  app_name: string;
  title: string;
  description: string | null;
  status: "pending" | "claimed" | "completed" | "expired" | "escalated";
  assignee_type: "person" | "role" | "group";
  due_at: string | null;
  created_at: string;
  workflow_name?: string;
}

export interface PortalActivity {
  id: string;
  app_id: string;
  app_name: string;
  type: "task_completed" | "task_created" | "alert" | "workflow_event" | "data_change";
  title: string;
  description: string | null;
  actor_name?: string;
  created_at: string;
}

export interface PortalDashboardData {
  apps: PortalApp[];
  tasks: PortalTask[];
  activity: PortalActivity[];
}

export interface PortalStats {
  total_apps: number;
  active_apps: number;
  pending_tasks: number;
  total_versions: number;
  recent_activity_count: number;
}

export interface SuggestedApp {
  department_id: string;
  department_name: string;
  suggestion: string;
}

export interface PortalStatsResponse {
  stats: PortalStats;
  suggestions: SuggestedApp[];
}

export interface PortalAppsResponse {
  apps: PortalApp[];
  total: number;
}

export interface PortalTasksResponse {
  tasks: PortalTask[];
  total: number;
}

export interface PortalActivityResponse {
  activity: PortalActivity[];
  total: number;
}

/** Export format options */
export type ExportFormat = "zip" | "dockerfile" | "git";

export interface ExportOptions {
  format: ExportFormat;
  includeReadme: boolean;
  includeDockerCompose: boolean;
  includeEnvExample: boolean;
  gitRemoteUrl?: string;
  gitBranch?: string;
}

export interface ExportResult {
  format: ExportFormat;
  success: boolean;
  message: string;
  downloadUrl?: string;
}

/** Command palette */
export interface CommandItem {
  id: string;
  label: string;
  description?: string;
  category: "navigation" | "action" | "model" | "component" | "page" | "workflow" | "rule";
  icon?: string;
  shortcut?: string;
  action: () => void;
}

/** Onboarding */
export type OnboardingStep =
  | "welcome"
  | "create_org"
  | "add_people"
  | "create_app"
  | "preview"
  | "complete";

export interface OnboardingState {
  currentStep: OnboardingStep;
  completedSteps: OnboardingStep[];
  dismissed: boolean;
}

/** Monitoring */
export interface CostEntry {
  date: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  agent_type: string;
}

export interface ProjectCostSummary {
  project_id: string;
  total_cost_usd: number;
  total_input_tokens: number;
  total_output_tokens: number;
  daily: CostEntry[];
  by_agent: Record<string, { cost_usd: number; calls: number }>;
}

export interface ErrorLogEntry {
  id: string;
  project_id: string;
  type: "agent_failure" | "build_failure" | "preview_crash" | "validation_error";
  message: string;
  details: string | null;
  agent_type: string | null;
  resolved: boolean;
  created_at: string;
}
