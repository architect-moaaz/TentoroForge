// Registers all @tentoroforge/library components into a single registry instance
// that the SchemaRenderer uses to resolve LibraryNode types at render time.
import {
  createRegistry,
  // Interactive
  Button, ButtonProps,
  IconButton, IconButtonProps,
  Link, LinkProps,
  // Form
  Form, FormProps,
  // Static
  Heading, HeadingProps,
  Badge, BadgeProps,
  Divider, DividerProps,
  Card, CardProps,
  EmptyState, EmptyStateProps,
  LoadingState, LoadingStateProps,
  Pagination, PaginationProps,
  // Data display
  Table, TableProps,
  TableSortable,
  // Feedback
  Alert, AlertProps,
  ConfirmDialog, ConfirmDialogProps,
  // Navigation
  NavLink, NavLinkProps,
  Breadcrumb, BreadcrumbProps,
  // Layout (v2 + marketing)
  Hero, HeroProps,
  Section, SectionProps,
  Split, SplitProps,
  Sidebar, SidebarProps,
  Cluster, ClusterProps,
  Tabs, TabsProps,
  Accordion, AccordionProps,
  AccordionPanel,
  // Static (v2 display)
  MetricTile, MetricTileProps,
  FeatureCard, FeatureCardProps,
  Avatar, AvatarProps,
  KeyValueList, KeyValueListProps,
  // Feedback (v2)
  Skeleton, SkeletonProps,
  // Form inputs (v2)
  Input, InputProps,
  Select, SelectProps,
  Textarea, TextareaProps,
  Checkbox, CheckboxProps,
  DatePicker, DatePickerProps,
  // Motion
  FadeIn, FadeInProps,
  Stagger, StaggerProps,
  // Custom
  CustomBlock, CustomBlockProps,
} from "@tentoroforge/library";
import { AccordionPanelNode } from "@tentoroforge/schema";
// App-local component: dynamic key/value display for jsonb columns.
// Registered below alongside the vendored @tentoroforge/library components.
import { ExtractedFieldsList, ExtractedFieldsListProps } from "./components/ExtractedFieldsList";

export const libraryRegistry = createRegistry();

libraryRegistry.register({ name: "Button",       component: Button,       propsSchema: ButtonProps,       category: "interactive",  acceptsChildren: false });
libraryRegistry.register({ name: "IconButton",   component: IconButton,   propsSchema: IconButtonProps,   category: "interactive",  acceptsChildren: false });
libraryRegistry.register({ name: "Link",         component: Link,         propsSchema: LinkProps,         category: "interactive",  acceptsChildren: false });

libraryRegistry.register({ name: "Form",         component: Form,         propsSchema: FormProps,         category: "form",         acceptsChildren: false });

libraryRegistry.register({ name: "Heading",      component: Heading,      propsSchema: HeadingProps,      category: "static",       acceptsChildren: false });
libraryRegistry.register({ name: "Badge",        component: Badge,        propsSchema: BadgeProps,        category: "static",       acceptsChildren: false });
libraryRegistry.register({ name: "Divider",      component: Divider,      propsSchema: DividerProps,      category: "static",       acceptsChildren: false });
libraryRegistry.register({ name: "Card",         component: Card,         propsSchema: CardProps,         category: "layout",       acceptsChildren: true  });
libraryRegistry.register({ name: "EmptyState",   component: EmptyState,   propsSchema: EmptyStateProps,   category: "feedback",     acceptsChildren: false });
libraryRegistry.register({ name: "LoadingState", component: LoadingState, propsSchema: LoadingStateProps, category: "feedback",     acceptsChildren: false });
libraryRegistry.register({ name: "Pagination",   component: Pagination,   propsSchema: PaginationProps,   category: "navigation",   acceptsChildren: false });

libraryRegistry.register({ name: "Table",        component: Table,        propsSchema: TableProps,        category: "data",         acceptsChildren: true  });
libraryRegistry.register({ name: "TableSortable",component: TableSortable,propsSchema: TableProps,        category: "data",         acceptsChildren: true  });

libraryRegistry.register({ name: "Alert",        component: Alert,        propsSchema: AlertProps,        category: "feedback",     acceptsChildren: false });
libraryRegistry.register({ name: "ConfirmDialog",component: ConfirmDialog,propsSchema: ConfirmDialogProps,category: "feedback",     acceptsChildren: false });

libraryRegistry.register({ name: "NavLink",      component: NavLink,      propsSchema: NavLinkProps,      category: "navigation",   acceptsChildren: false });
libraryRegistry.register({ name: "Breadcrumb",   component: Breadcrumb,   propsSchema: BreadcrumbProps,   category: "navigation",   acceptsChildren: false });

// Layout (v2 nodes + foundation marketing)
libraryRegistry.register({ name: "Hero",          component: Hero,          propsSchema: HeroProps,          category: "layout",       acceptsChildren: true  });
libraryRegistry.register({ name: "Section",       component: Section,       propsSchema: SectionProps,       category: "layout",       acceptsChildren: true  });
libraryRegistry.register({ name: "Split",         component: Split,         propsSchema: SplitProps,         category: "layout",       acceptsChildren: true  });
libraryRegistry.register({ name: "Sidebar",       component: Sidebar,       propsSchema: SidebarProps,       category: "layout",       acceptsChildren: true  });
libraryRegistry.register({ name: "Cluster",       component: Cluster,       propsSchema: ClusterProps,       category: "layout",       acceptsChildren: true  });
libraryRegistry.register({ name: "Tabs",          component: Tabs,          propsSchema: TabsProps,          category: "layout",       acceptsChildren: true  });
libraryRegistry.register({ name: "Accordion",     component: Accordion,     propsSchema: AccordionProps,     category: "layout",       acceptsChildren: true  });
libraryRegistry.register({ name: "AccordionPanel",component: AccordionPanel,propsSchema: AccordionPanelNode.shape.props,                                                     category: "layout", acceptsChildren: true  });

// Static (v2 display)
libraryRegistry.register({ name: "MetricTile",    component: MetricTile,    propsSchema: MetricTileProps,    category: "static",       acceptsChildren: false });
libraryRegistry.register({ name: "FeatureCard",   component: FeatureCard,   propsSchema: FeatureCardProps,   category: "static",       acceptsChildren: false });
libraryRegistry.register({ name: "Avatar",        component: Avatar,        propsSchema: AvatarProps,        category: "static",       acceptsChildren: false });
libraryRegistry.register({ name: "KeyValueList",  component: KeyValueList,  propsSchema: KeyValueListProps,  category: "static",       acceptsChildren: false });

// Feedback (v2)
libraryRegistry.register({ name: "Skeleton",      component: Skeleton,      propsSchema: SkeletonProps,      category: "feedback",     acceptsChildren: false });

// Form inputs (v2)
libraryRegistry.register({ name: "Input",         component: Input,         propsSchema: InputProps,         category: "form",         acceptsChildren: false });
libraryRegistry.register({ name: "Select",        component: Select,        propsSchema: SelectProps,        category: "form",         acceptsChildren: false });
libraryRegistry.register({ name: "Textarea",      component: Textarea,      propsSchema: TextareaProps,      category: "form",         acceptsChildren: false });
libraryRegistry.register({ name: "Checkbox",      component: Checkbox,      propsSchema: CheckboxProps,      category: "form",         acceptsChildren: false });
libraryRegistry.register({ name: "DatePicker",    component: DatePicker,    propsSchema: DatePickerProps,    category: "form",         acceptsChildren: false });

// Motion
libraryRegistry.register({ name: "FadeIn",        component: FadeIn,        propsSchema: FadeInProps,        category: "motion",       acceptsChildren: true  });
libraryRegistry.register({ name: "Stagger",       component: Stagger,       propsSchema: StaggerProps,       category: "motion",       acceptsChildren: true  });

// Custom
libraryRegistry.register({ name: "CustomBlock",           component: CustomBlock,           propsSchema: CustomBlockProps,           category: "custom",       acceptsChildren: false });
libraryRegistry.register({ name: "ExtractedFieldsList",   component: ExtractedFieldsList,   propsSchema: ExtractedFieldsListProps,   category: "custom",       acceptsChildren: false });
