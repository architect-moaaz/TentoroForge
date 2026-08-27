"use client";

import {
  Package,
  Monitor,
  Users,
  FileText,
  Calendar,
  UserSearch,
  Receipt,
  CreditCard,
  LifeBuoy,
  BookOpen,
  Server,
  Megaphone,
  CalendarDays,
  Scale,
  FileCheck,
  LucideIcon,
  Layout,
} from "lucide-react";
import { Card, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

const ICON_MAP: Record<string, LucideIcon> = {
  Package,
  Monitor,
  Users,
  FileText,
  Calendar,
  UserSearch,
  Receipt,
  CreditCard,
  LifeBuoy,
  BookOpen,
  Server,
  Megaphone,
  CalendarDays,
  Scale,
  FileCheck,
};

const COMPLEXITY_COLORS: Record<string, string> = {
  simple: "bg-green-100 text-green-700",
  moderate: "bg-yellow-100 text-yellow-700",
  complex: "bg-red-100 text-red-700",
};

interface TemplateCardProps {
  template: {
    slug: string;
    name: string;
    description: string | null;
    category: string;
    icon: string | null;
    complexity: string | null;
    tags: string[] | null;
  };
  onClick: () => void;
}

export function TemplateCard({ template, onClick }: TemplateCardProps) {
  const Icon = ICON_MAP[template.icon || ""] || Layout;

  return (
    <button onClick={onClick} className="text-left">
      <Card className="h-full transition-shadow hover:shadow-md">
        <CardHeader>
          <div className="mb-2 flex items-start justify-between">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
              <Icon className="h-5 w-5 text-primary" />
            </div>
            {template.complexity && (
              <Badge
                variant="secondary"
                className={`text-xs ${COMPLEXITY_COLORS[template.complexity] || ""}`}
              >
                {template.complexity}
              </Badge>
            )}
          </div>
          <CardTitle className="text-base">{template.name}</CardTitle>
          <CardDescription className="line-clamp-2 text-xs">
            {template.description}
          </CardDescription>
          <div className="pt-1">
            <Badge variant="outline" className="text-xs">
              {template.category}
            </Badge>
          </div>
        </CardHeader>
      </Card>
    </button>
  );
}
