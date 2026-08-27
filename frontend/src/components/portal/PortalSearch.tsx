"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  AppWindow,
  ClipboardCheck,
  LayoutDashboard,
  Settings,
  Users,
} from "lucide-react";
import { api } from "@/lib/api";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Dialog,
  DialogContent,
} from "@/components/ui/dialog";
import { usePortalStore } from "@/stores/portal";
import type { PortalAppsResponse } from "@/types/portal";

interface PortalSearchProps {
  orgId: string;
}

export function PortalSearch({ orgId }: PortalSearchProps) {
  const router = useRouter();
  const open = usePortalStore((s) => s.commandPaletteOpen);
  const setOpen = usePortalStore((s) => s.setCommandPaletteOpen);

  const { data } = useQuery({
    queryKey: ["org", orgId, "portal", "apps"],
    queryFn: () =>
      api.get<PortalAppsResponse>(`/api/orgs/${orgId}/portal/apps`),
    enabled: open,
  });

  const apps = data?.apps ?? [];

  // Cmd+K shortcut
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen(!open);
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open, setOpen]);

  const navigate = useCallback(
    (path: string) => {
      setOpen(false);
      router.push(path);
    },
    [router, setOpen]
  );

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="overflow-hidden p-0 shadow-lg sm:max-w-[500px] [&>button]:hidden">
        <Command className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground">
          <CommandInput placeholder="Search apps, pages, actions..." />
          <CommandList>
            <CommandEmpty>No results found.</CommandEmpty>

            {/* Navigation */}
            <CommandGroup heading="Navigation">
              <CommandItem onSelect={() => navigate(`/org/${orgId}/portal`)}>
                <LayoutDashboard className="mr-2 h-4 w-4" />
                Portal Dashboard
              </CommandItem>
              <CommandItem onSelect={() => navigate(`/org/${orgId}/projects`)}>
                <AppWindow className="mr-2 h-4 w-4" />
                All Projects
              </CommandItem>
              <CommandItem onSelect={() => navigate(`/org/${orgId}/people`)}>
                <Users className="mr-2 h-4 w-4" />
                People
              </CommandItem>
              <CommandItem onSelect={() => navigate(`/org/${orgId}/settings`)}>
                <Settings className="mr-2 h-4 w-4" />
                Settings
              </CommandItem>
            </CommandGroup>

            {/* Apps */}
            {apps.length > 0 && (
              <CommandGroup heading="Applications">
                {apps.map((app) => (
                  <CommandItem
                    key={app.id}
                    value={`${app.name} ${app.description || ""}`}
                    onSelect={() =>
                      navigate(`/org/${orgId}/projects/${app.id}`)
                    }
                  >
                    <AppWindow className="mr-2 h-4 w-4" />
                    <div className="flex flex-col">
                      <span>{app.name}</span>
                      {app.description && (
                        <span className="text-xs text-muted-foreground">
                          {app.description}
                        </span>
                      )}
                    </div>
                    {app.badges.pending_tasks > 0 && (
                      <span className="ml-auto flex items-center gap-1 text-xs text-amber-600">
                        <ClipboardCheck className="h-3 w-3" />
                        {app.badges.pending_tasks}
                      </span>
                    )}
                  </CommandItem>
                ))}
              </CommandGroup>
            )}
          </CommandList>
        </Command>
      </DialogContent>
    </Dialog>
  );
}
