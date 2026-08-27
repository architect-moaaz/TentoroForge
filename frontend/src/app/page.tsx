"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { AuthGuard } from "@/components/auth-guard";
import { useAuthStore } from "@/stores/auth";
import { api, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface Org {
  id: string;
  name: string;
  slug: string;
  logo_url: string | null;
  created_at: string;
}

function OrgSelector() {
  const router = useRouter();
  const { user, logout } = useAuthStore();
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const { data: orgs = [], refetch } = useQuery({
    queryKey: ["orgs"],
    queryFn: () => api.get<Org[]>("/api/orgs"),
  });

  function handleNameChange(value: string) {
    setName(value);
    setSlug(value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""));
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setCreating(true);
    setCreateError(null);
    try {
      const org = await api.post<Org>("/api/orgs", { name, slug });
      setShowCreate(false);
      setName("");
      setSlug("");
      refetch();
      router.push(`/org/${org.id}`);
    } catch (err) {
      // Surface it — a swallowed 409 ("Slug already taken") looks like a
      // dead button and invites the user to click Create over and over.
      setCreateError(
        err instanceof ApiError ? err.message : "Could not create organization",
      );
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="flex min-h-screen flex-col bg-gradient-to-br from-background via-background to-primary/5">
      {/* Header */}
      <header className="sticky top-0 z-10 flex items-center justify-between border-b bg-white/80 backdrop-blur-md px-6 py-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary text-sm font-bold text-primary-foreground shadow-sm">
            T
          </div>
          <div>
            <h1 className="text-base font-semibold tracking-tight">Tentoro Forge</h1>
            <p className="text-[10px] text-muted-foreground -mt-0.5">Build apps with AI</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 rounded-full bg-muted/50 px-3 py-1.5">
            <div className="flex h-6 w-6 items-center justify-center rounded-full bg-primary/10 text-[10px] font-semibold text-primary">
              {user?.email?.[0]?.toUpperCase() || "U"}
            </div>
            <span className="text-xs text-muted-foreground">{user?.email}</span>
          </div>
          <Button variant="ghost" size="sm" className="text-xs text-muted-foreground hover:text-foreground" onClick={logout}>
            Sign out
          </Button>
        </div>
      </header>

      <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col px-6 py-10 md:px-8">
        {/* Hero section */}
        <div className="mb-10 flex flex-col sm:flex-row sm:items-end justify-between gap-4">
          <div>
            <p className="text-xs font-medium uppercase tracking-widest text-primary mb-2">Workspace</p>
            <h2 className="text-3xl font-bold tracking-tight">Your Organizations</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Select an organization to start building, or create a new one.
            </p>
          </div>
          <Dialog open={showCreate} onOpenChange={setShowCreate}>
            <DialogTrigger asChild>
              <Button className="rounded-xl shadow-sm transition-all hover:shadow-md active:scale-[0.98]">
                <Plus className="mr-2 h-4 w-4" />
                Create Organization
              </Button>
            </DialogTrigger>
            <DialogContent className="sm:max-w-md">
              <form onSubmit={handleCreate}>
                <DialogHeader>
                  <DialogTitle>Create Organization</DialogTitle>
                  <DialogDescription>
                    Set up a new workspace for your team
                  </DialogDescription>
                </DialogHeader>
                <div className="space-y-4 py-4">
                  <div className="space-y-2">
                    <Label htmlFor="org-name">Organization name</Label>
                    <Input
                      id="org-name"
                      className="rounded-lg"
                      placeholder="Acme Corp"
                      value={name}
                      onChange={(e) => handleNameChange(e.target.value)}
                      required
                      autoFocus
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="org-slug">URL slug</Label>
                    {/* `-` escaped in `pattern`: browsers compile it with the
                        `v` flag, where a bare `-` in a character class is a
                        syntax error rather than a literal hyphen. */}
                    <Input
                      id="org-slug"
                      className="rounded-lg font-mono text-sm"
                      placeholder="acme-corp"
                      value={slug}
                      onChange={(e) => setSlug(e.target.value)}
                      required
                      pattern="[a-z0-9\-]+"
                    />
                    <p className="text-[10px] text-muted-foreground">
                      Lowercase letters, numbers, and hyphens only
                    </p>
                  </div>
                  {createError && (
                    <p className="text-xs font-medium text-destructive">
                      {createError}
                    </p>
                  )}
                </div>
                <DialogFooter>
                  <Button
                    type="button"
                    variant="outline"
                    className="rounded-lg"
                    onClick={() => setShowCreate(false)}
                  >
                    Cancel
                  </Button>
                  <Button type="submit" className="rounded-lg" disabled={creating}>
                    {creating ? "Creating..." : "Create"}
                  </Button>
                </DialogFooter>
              </form>
            </DialogContent>
          </Dialog>
        </div>

        {orgs.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <div className="rounded-2xl bg-primary/10 p-5 mb-5">
              <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-primary text-2xl font-bold text-primary-foreground shadow-md">
                T
              </div>
            </div>
            <h3 className="text-xl font-semibold">No organizations yet</h3>
            <p className="mt-2 text-sm text-muted-foreground max-w-sm">
              Create your first organization to start building apps with AI-powered code generation.
            </p>
            <Button className="mt-6 rounded-xl shadow-sm" onClick={() => setShowCreate(true)}>
              <Plus className="mr-2 h-4 w-4" />
              Create Your First Organization
            </Button>
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {orgs.map((org, i) => {
              const colors = [
                "from-primary to-primary/80",
                "from-primary/90 to-primary/70",
                "from-primary/80 to-primary/60",
                "from-primary to-primary/90",
                "from-primary/85 to-primary/65",
                "from-primary/95 to-primary/75",
              ];
              const gradient = colors[i % colors.length];

              return (
                <Card
                  key={org.id}
                  // BUG-002: the base Card primitive adds `py-6`, which pushed the
                  // gradient accent bar 24px DOWN from the top — a square-cornered
                  // strip floating in the card body instead of a flush top accent
                  // clipped to the rounded corners. `py-0` makes it flush (the
                  // card's overflow-hidden + rounded-2xl then round its corners);
                  // the CardHeader below carries its own padding.
                  className="group cursor-pointer rounded-2xl border-0 py-0 shadow-sm transition-all duration-200 hover:shadow-lg hover:-translate-y-1 bg-white overflow-hidden"
                  onClick={() => router.push(`/org/${org.id}`)}
                >
                  {/* Gradient top accent */}
                  <div className={`h-1.5 bg-gradient-to-r ${gradient}`} />
                  <CardHeader className="pt-5 pb-5">
                    <div className="flex items-center gap-4">
                      <div className={`flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br ${gradient} text-lg font-bold text-white shadow-sm transition-transform group-hover:scale-105`}>
                        {org.name[0]?.toUpperCase()}
                      </div>
                      <div className="flex-1 min-w-0">
                        <CardTitle className="text-base font-semibold truncate">{org.name}</CardTitle>
                        <CardDescription className="text-xs font-mono mt-0.5">
                          /{org.slug}
                        </CardDescription>
                      </div>
                      <div className="shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                        <svg className="h-5 w-5 text-muted-foreground" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                        </svg>
                      </div>
                    </div>
                  </CardHeader>
                </Card>
              );
            })}

            {/* Create new org card */}
            <Card
              className="cursor-pointer rounded-2xl border-2 border-dashed border-muted-foreground/20 shadow-none transition-all duration-200 hover:border-primary/30 hover:bg-primary/5 bg-transparent"
              onClick={() => setShowCreate(true)}
            >
              <CardHeader className="flex items-center justify-center py-8">
                <div className="flex flex-col items-center gap-2 text-muted-foreground">
                  <div className="rounded-xl border-2 border-dashed border-muted-foreground/30 p-3">
                    <Plus className="h-5 w-5" />
                  </div>
                  <span className="text-xs font-medium">New Organization</span>
                </div>
              </CardHeader>
            </Card>
          </div>
        )}

        {/* Footer — BUG-003: main is now a flex column and the footer uses
            `mt-auto` so it sits at the bottom of the viewport instead of
            floating mid-page with ~186px of dead space below it. */}
        <div className="mt-auto pt-6 pb-4 border-t flex items-center justify-between">
          <p className="text-[10px] text-muted-foreground">
            Tentoro Forge — AI-powered application builder
          </p>
          <p className="text-[10px] text-muted-foreground">
            {orgs.length} organization{orgs.length !== 1 ? "s" : ""}
          </p>
        </div>
      </main>
    </div>
  );
}

export default function Home() {
  return (
    <AuthGuard>
      <OrgSelector />
    </AuthGuard>
  );
}
