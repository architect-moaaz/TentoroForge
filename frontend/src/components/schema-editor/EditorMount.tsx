"use client";

import { useMemo } from "react";
import { AccordionPanelNode } from "@tentoroforge/schema";
import { Editor } from "@tentoroforge/editor";
import { createRegistry, defaultTokens } from "@tentoroforge/library";

// Individual components
import { Button } from "@tentoroforge/library";
import { ButtonProps } from "@tentoroforge/library";
import { IconButton } from "@tentoroforge/library";
import { IconButtonProps } from "@tentoroforge/library";
import { Link } from "@tentoroforge/library";
import { LinkProps } from "@tentoroforge/library";
import { Form } from "@tentoroforge/library";
import { FormProps } from "@tentoroforge/library";
import { Heading } from "@tentoroforge/library";
import { HeadingProps } from "@tentoroforge/library";
import { Badge } from "@tentoroforge/library";
import { BadgeProps } from "@tentoroforge/library";
import { Divider } from "@tentoroforge/library";
import { DividerProps } from "@tentoroforge/library";
import { Card } from "@tentoroforge/library";
import { CardProps } from "@tentoroforge/library";
import { EmptyState } from "@tentoroforge/library";
import { EmptyStateProps } from "@tentoroforge/library";
import { LoadingState } from "@tentoroforge/library";
import { LoadingStateProps } from "@tentoroforge/library";
import { Pagination } from "@tentoroforge/library";
import { PaginationProps } from "@tentoroforge/library";
import { Table } from "@tentoroforge/library";
import { TableProps } from "@tentoroforge/library";
import { Alert } from "@tentoroforge/library";
import { AlertProps } from "@tentoroforge/library";
import { ConfirmDialog } from "@tentoroforge/library";
import { ConfirmDialogProps } from "@tentoroforge/library";
import { NavLink } from "@tentoroforge/library";
import { NavLinkProps } from "@tentoroforge/library";
import { Breadcrumb } from "@tentoroforge/library";
import { BreadcrumbProps } from "@tentoroforge/library";
import { Hero } from "@tentoroforge/library";
import { HeroProps } from "@tentoroforge/library";
import { Section } from "@tentoroforge/library";
import { SectionProps } from "@tentoroforge/library";
import { Split } from "@tentoroforge/library";
import { SplitProps } from "@tentoroforge/library";
import { Sidebar } from "@tentoroforge/library";
import { SidebarProps } from "@tentoroforge/library";
import { Cluster } from "@tentoroforge/library";
import { ClusterProps } from "@tentoroforge/library";
import { Tabs } from "@tentoroforge/library";
import { TabsProps } from "@tentoroforge/library";
import { Accordion } from "@tentoroforge/library";
import { AccordionProps } from "@tentoroforge/library";
import { AccordionPanel } from "@tentoroforge/library";
import { TableSortable } from "@tentoroforge/library";
import { MetricTile } from "@tentoroforge/library";
import { MetricTileProps } from "@tentoroforge/library";
import { FeatureCard } from "@tentoroforge/library";
import { FeatureCardProps } from "@tentoroforge/library";
import { Avatar } from "@tentoroforge/library";
import { AvatarProps } from "@tentoroforge/library";
import { KeyValueList } from "@tentoroforge/library";
import { KeyValueListProps } from "@tentoroforge/library";
import { Skeleton } from "@tentoroforge/library";
import { SkeletonProps } from "@tentoroforge/library";
import { Input } from "@tentoroforge/library";
import { InputProps } from "@tentoroforge/library";
import { Select } from "@tentoroforge/library";
import { SelectProps } from "@tentoroforge/library";
import { Textarea } from "@tentoroforge/library";
import { TextareaProps } from "@tentoroforge/library";
import { Checkbox } from "@tentoroforge/library";
import { CheckboxProps } from "@tentoroforge/library";
import { DatePicker } from "@tentoroforge/library";
import { DatePickerProps } from "@tentoroforge/library";
import { FadeIn } from "@tentoroforge/library";
import { FadeInProps } from "@tentoroforge/library";
import { Stagger } from "@tentoroforge/library";
import { StaggerProps } from "@tentoroforge/library";
import { TabPanel } from "@tentoroforge/library";
import { TabPanelProps } from "@tentoroforge/library";
import { CustomBlock } from "@tentoroforge/library";
import { CustomBlockProps } from "@tentoroforge/library";

// Build the library registry once at module load time.
// createRegistry() returns a new empty registry — we register all standard
// library components so the editor's Palette and Canvas can render them.
function buildDefaultRegistry() {
  const reg = createRegistry();

  // Interactive
  reg.register({ name: "Button", component: Button, propsSchema: ButtonProps, category: "interactive", acceptsChildren: false });
  reg.register({ name: "IconButton", component: IconButton, propsSchema: IconButtonProps, category: "interactive", acceptsChildren: false });
  reg.register({ name: "Link", component: Link, propsSchema: LinkProps, category: "interactive", acceptsChildren: false });

  // Form
  reg.register({ name: "Form", component: Form, propsSchema: FormProps, category: "form", acceptsChildren: true });

  // Static
  reg.register({ name: "Heading", component: Heading, propsSchema: HeadingProps, category: "static", acceptsChildren: false });
  reg.register({ name: "Badge", component: Badge, propsSchema: BadgeProps, category: "static", acceptsChildren: false });
  reg.register({ name: "Divider", component: Divider, propsSchema: DividerProps, category: "static", acceptsChildren: false });
  reg.register({ name: "Card", component: Card, propsSchema: CardProps, category: "static", acceptsChildren: true });
  reg.register({ name: "EmptyState", component: EmptyState, propsSchema: EmptyStateProps, category: "static", acceptsChildren: false });
  reg.register({ name: "LoadingState", component: LoadingState, propsSchema: LoadingStateProps, category: "static", acceptsChildren: false });
  reg.register({ name: "Pagination", component: Pagination, propsSchema: PaginationProps, category: "static", acceptsChildren: false });

  // Data
  reg.register({ name: "Table",         component: Table,         propsSchema: TableProps, category: "data", acceptsChildren: false });
  reg.register({ name: "TableSortable", component: TableSortable, propsSchema: TableProps, category: "data", acceptsChildren: true  });

  // Feedback
  reg.register({ name: "Alert", component: Alert, propsSchema: AlertProps, category: "feedback", acceptsChildren: false });
  reg.register({ name: "ConfirmDialog", component: ConfirmDialog, propsSchema: ConfirmDialogProps, category: "feedback", acceptsChildren: false });

  // Navigation
  reg.register({ name: "NavLink", component: NavLink, propsSchema: NavLinkProps, category: "navigation", acceptsChildren: false });
  reg.register({ name: "Breadcrumb", component: Breadcrumb, propsSchema: BreadcrumbProps, category: "navigation", acceptsChildren: false });

  // Layout (v2 nodes + foundation marketing)
  reg.register({ name: "Hero", component: Hero, propsSchema: HeroProps, category: "layout", acceptsChildren: true });
  reg.register({ name: "Section", component: Section, propsSchema: SectionProps, category: "layout", acceptsChildren: true });
  reg.register({ name: "Split", component: Split, propsSchema: SplitProps, category: "layout", acceptsChildren: true });
  reg.register({ name: "Sidebar", component: Sidebar, propsSchema: SidebarProps, category: "layout", acceptsChildren: true });
  reg.register({ name: "Cluster", component: Cluster, propsSchema: ClusterProps, category: "layout", acceptsChildren: true });
  reg.register({ name: "Tabs", component: Tabs, propsSchema: TabsProps, category: "layout", acceptsChildren: true });
  reg.register({ name: "Accordion", component: Accordion, propsSchema: AccordionProps, category: "layout", acceptsChildren: true });
  reg.register({ name: "AccordionPanel", component: AccordionPanel, propsSchema: AccordionPanelNode.shape.props, category: "layout", acceptsChildren: true });

  // Static (v2 display + foundation building blocks)
  reg.register({ name: "MetricTile", component: MetricTile, propsSchema: MetricTileProps, category: "static", acceptsChildren: false });
  reg.register({ name: "FeatureCard", component: FeatureCard, propsSchema: FeatureCardProps, category: "static", acceptsChildren: false });
  reg.register({ name: "Avatar", component: Avatar, propsSchema: AvatarProps, category: "static", acceptsChildren: false });
  reg.register({ name: "KeyValueList", component: KeyValueList, propsSchema: KeyValueListProps, category: "static", acceptsChildren: false });

  // Feedback
  reg.register({ name: "Skeleton", component: Skeleton, propsSchema: SkeletonProps, category: "feedback", acceptsChildren: false });

  // Form inputs
  reg.register({ name: "Input", component: Input, propsSchema: InputProps, category: "form", acceptsChildren: false });
  reg.register({ name: "Select", component: Select, propsSchema: SelectProps, category: "form", acceptsChildren: false });
  reg.register({ name: "Textarea", component: Textarea, propsSchema: TextareaProps, category: "form", acceptsChildren: false });
  reg.register({ name: "Checkbox", component: Checkbox, propsSchema: CheckboxProps, category: "form", acceptsChildren: false });
  reg.register({ name: "DatePicker", component: DatePicker, propsSchema: DatePickerProps, category: "form", acceptsChildren: false });

  // Motion
  reg.register({ name: "FadeIn", component: FadeIn, propsSchema: FadeInProps, category: "motion", acceptsChildren: true });
  reg.register({ name: "Stagger", component: Stagger, propsSchema: StaggerProps, category: "motion", acceptsChildren: true });

  // TabPanel — passthrough wrapper for LLM-generated <Tabs><TabPanel>...
  reg.register({ name: "TabPanel", component: TabPanel, propsSchema: TabPanelProps, category: "layout", acceptsChildren: true });

  // Custom
  reg.register({ name: "CustomBlock", component: CustomBlock, propsSchema: CustomBlockProps, category: "custom", acceptsChildren: false });

  return reg;
}

// Singleton registry — built once at module load.
// This is safe because the component list is static per version of the library.
const defaultRegistry = buildDefaultRegistry();

export type EditorMountProps = {
  projectId: string;
  schemaPath: string;
};

/**
 * Client component that owns the library registry + default tokens and
 * renders the <Editor /> from @tentoroforge/editor.
 *
 * Receives projectId + schemaPath from server-component route pages, which
 * read those values from Next.js dynamic params.
 */
export function EditorMount({ projectId, schemaPath }: EditorMountProps) {
  return (
    <Editor
      initialSchemaPath={schemaPath || undefined}
      registry={defaultRegistry}
      tokens={defaultTokens}
      apiBaseUrl={`/api/projects/${projectId}`}
    />
  );
}
