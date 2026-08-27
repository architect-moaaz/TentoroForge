"use client";

import { use, useState, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  Users,
  Building2,
  UsersRound,
  Network,
  FolderOpen,
  Sparkles,
  ArrowRight,
  ArrowUpRight,
} from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { OnboardingTutorial } from "@/components/onboarding/OnboardingTutorial";
import { OnboardingWizardDialog } from "@/components/onboarding/OnboardingWizardDialog";

interface Person { id: string }
interface Department { id: string }
interface Team { id: string }
interface TemplateInfo {
  slug: string; name: string; description: string | null;
  category: string; icon: string | null; complexity: string | null;
}
interface SuggestedTemplate {
  template: TemplateInfo; score: number;
  matching_departments: string[]; reason: string;
}
interface SuggestedResponse {
  suggestions: SuggestedTemplate[]; org_departments: string[];
}

function OrgDashboard({ orgId }: { orgId: string }) {
  const router = useRouter();
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [showWizard, setShowWizard] = useState(false);

  useEffect(() => {
    const dismissed = localStorage.getItem(`tentoroforge_onboarding_${orgId}_dismissed`);
    const wizardDone = localStorage.getItem(`tentoroforge_wizard_completed_${orgId}`);
    if (!dismissed) setShowOnboarding(true);
    if (!wizardDone) setShowWizard(true);
  }, [orgId]);

  const handleDismissOnboarding = () => {
    setShowOnboarding(false);
    localStorage.setItem(`tentoroforge_onboarding_${orgId}_dismissed`, "true");
  };

  const { data: people = [] } = useQuery({
    queryKey: ["org", orgId, "people"],
    queryFn: () => api.get<Person[]>(`/api/orgs/${orgId}/people`),
  });
  const { data: departments = [] } = useQuery({
    queryKey: ["org", orgId, "departments"],
    queryFn: () => api.get<Department[]>(`/api/orgs/${orgId}/departments`),
  });
  const { data: teams = [] } = useQuery({
    queryKey: ["org", orgId, "teams"],
    queryFn: () => api.get<Team[]>(`/api/orgs/${orgId}/teams`),
  });
  const { data: suggested } = useQuery({
    queryKey: ["org", orgId, "suggested-apps"],
    queryFn: () => api.get<SuggestedResponse>(`/api/orgs/${orgId}/suggested-apps`),
  });

  const stats = [
    { label: "Projects", value: "View", icon: FolderOpen, href: `/org/${orgId}/projects`, color: "bg-blue-50 text-blue-600 dark:bg-blue-950 dark:text-blue-400" },
    { label: "People", value: people.length, icon: Users, href: `/org/${orgId}/people`, color: "bg-emerald-50 text-emerald-600 dark:bg-emerald-950 dark:text-emerald-400" },
    { label: "Departments", value: departments.length, icon: Building2, href: `/org/${orgId}/departments`, color: "bg-amber-50 text-amber-600 dark:bg-amber-950 dark:text-amber-400" },
    { label: "Teams", value: teams.length, icon: UsersRound, href: `/org/${orgId}/teams`, color: "bg-violet-50 text-violet-600 dark:bg-violet-950 dark:text-violet-400" },
  ];

  return (
    <div className="p-8">
      {/* Page header */}
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-foreground">Dashboard</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Overview of your organization
          </p>
        </div>
      </div>

      {/* Onboarding */}
      {showOnboarding && (
        <div className="mb-8">
          <OnboardingTutorial
            orgId={orgId}
            onDismiss={handleDismissOnboarding}
            onNavigate={(path) => router.push(path)}
          />
        </div>
      )}

      {/* Stats grid */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 mb-10">
        {stats.map(({ label, value, icon: Icon, href, color }) => (
          <Link key={label} href={href} className="group">
            <div className="flex items-center gap-4 rounded-xl border border-slate-200/80 bg-white p-4 transition-all duration-150 hover:border-slate-300 hover:shadow-sm dark:border-slate-800 dark:bg-slate-900 dark:hover:border-slate-700">
              <div className={`flex h-10 w-10 items-center justify-center rounded-lg ${color}`}>
                <Icon className="h-[18px] w-[18px]" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-[13px] text-slate-500 dark:text-slate-400">{label}</p>
                <p className="text-lg font-semibold text-slate-900 dark:text-white">{value}</p>
              </div>
              <ArrowUpRight className="h-4 w-4 text-slate-300 opacity-0 transition-opacity group-hover:opacity-100 dark:text-slate-600" />
            </div>
          </Link>
        ))}
      </div>

      {/* Quick actions */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 mb-10">
        <Link href={`/org/${orgId}/projects`} className="group">
          <div className="relative overflow-hidden rounded-xl border border-slate-200/80 bg-white p-5 transition-all hover:border-slate-300 hover:shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <div className="absolute top-0 right-0 h-24 w-24 rounded-bl-[80px] bg-gradient-to-br from-blue-50 to-blue-100/50 dark:from-blue-950/30 dark:to-transparent" />
            <FolderOpen className="h-5 w-5 text-blue-600 mb-3 relative z-10" />
            <h3 className="text-sm font-semibold text-slate-900 dark:text-white relative z-10">View Projects</h3>
            <p className="mt-1 text-xs text-slate-500 relative z-10">Open existing projects or create new ones</p>
          </div>
        </Link>
        <Link href={`/org/${orgId}/discover`} className="group">
          <div className="relative overflow-hidden rounded-xl border border-slate-200/80 bg-white p-5 transition-all hover:border-slate-300 hover:shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <div className="absolute top-0 right-0 h-24 w-24 rounded-bl-[80px] bg-gradient-to-br from-amber-50 to-amber-100/50 dark:from-amber-950/30 dark:to-transparent" />
            <Sparkles className="h-5 w-5 text-amber-600 mb-3 relative z-10" />
            <h3 className="text-sm font-semibold text-slate-900 dark:text-white relative z-10">Discover</h3>
            <p className="mt-1 text-xs text-slate-500 relative z-10">Find the right app for your team with AI</p>
          </div>
        </Link>
        <Link href={`/org/${orgId}/org-chart`} className="group">
          <div className="relative overflow-hidden rounded-xl border border-slate-200/80 bg-white p-5 transition-all hover:border-slate-300 hover:shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <div className="absolute top-0 right-0 h-24 w-24 rounded-bl-[80px] bg-gradient-to-br from-violet-50 to-violet-100/50 dark:from-violet-950/30 dark:to-transparent" />
            <Network className="h-5 w-5 text-violet-600 mb-3 relative z-10" />
            <h3 className="text-sm font-semibold text-slate-900 dark:text-white relative z-10">Org Chart</h3>
            <p className="mt-1 text-xs text-slate-500 relative z-10">Visualize your team structure</p>
          </div>
        </Link>
      </div>

      {/* Suggested Apps */}
      {suggested && suggested.suggestions.length > 0 && (
        <div>
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold text-slate-900 dark:text-white">Suggested for you</h2>
              <p className="text-xs text-slate-500 mt-0.5">Based on your organization structure</p>
            </div>
            <Link href={`/org/${orgId}/discover`}>
              <Button variant="ghost" size="sm" className="gap-1 text-xs text-slate-500 hover:text-slate-700">
                See all
                <ArrowRight className="h-3 w-3" />
              </Button>
            </Link>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {suggested.suggestions.slice(0, 6).map(({ template, reason }) => (
              <Link key={template.slug} href={`/org/${orgId}/templates`}>
                <div className="rounded-xl border border-slate-200/80 bg-white p-4 transition-all hover:border-slate-300 hover:shadow-sm dark:border-slate-800 dark:bg-slate-900">
                  <div className="flex items-start justify-between mb-2">
                    <h3 className="text-sm font-medium text-slate-900 dark:text-white">
                      {template.name}
                    </h3>
                    <span className="rounded-md bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-400">
                      {template.category}
                    </span>
                  </div>
                  <p className="text-xs text-slate-500 line-clamp-2">
                    {template.description}
                  </p>
                  <p className="mt-2 text-[11px] text-blue-600 dark:text-blue-400">
                    {reason}
                  </p>
                </div>
              </Link>
            ))}
          </div>
        </div>
      )}

      <OnboardingWizardDialog
        orgId={orgId}
        open={showWizard}
        onOpenChange={setShowWizard}
        onNavigate={(path) => router.push(path)}
      />
    </div>
  );
}

export default function OrgDashboardPage({
  params,
}: {
  params: Promise<{ orgId: string }>;
}) {
  const { orgId } = use(params);
  return <OrgDashboard orgId={orgId} />;
}
