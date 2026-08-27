/**
 * buildDefaultRegistry — single source of truth for component registration.
 *
 * Both the scaffold (SchemaRendererWrapper) and the engine (Engine.tsx) import
 * this instead of maintaining separate copies. Any new component added here
 * automatically appears in both the standalone render path and the editor
 * canvas preview.
 *
 * The `illustrationBasePath` option threads the per-project illustration
 * base URL into Hero / Section / EmptyStateRich without forcing LLM-emitted
 * schemas to carry that plumbing directly.
 */

import * as React from "react";
import { createRegistry } from "./registry";
import type { Registry, LibraryCategory, ChildContract } from "./registry";

// Interactive
import { Button } from "./components/Button/Button";
import { ButtonProps } from "./components/Button/Button.schema";
import { Link } from "./components/Link/Link";
import { LinkProps } from "./components/Link/Link.schema";
import { NavLink } from "./components/NavLink/NavLink";
import { NavLinkProps } from "./components/NavLink/NavLink.schema";
import { IconButton } from "./components/IconButton/IconButton";
import { IconButtonProps } from "./components/IconButton/IconButton.schema";

// Layout / structure
import { Hero } from "./components/Hero/Hero";
import { HeroProps } from "./components/Hero/Hero.schema";
import { Section } from "./components/Section/Section";
import { SectionProps } from "./components/Section/Section.schema";
import { Split } from "./components/Split/Split";
import { SplitProps } from "./components/Split/Split.schema";
import { Sidebar } from "./components/Sidebar/Sidebar";
import { SidebarProps } from "./components/Sidebar/Sidebar.schema";
import { Cluster } from "./components/Cluster/Cluster";
import { ClusterProps } from "./components/Cluster/Cluster.schema";
import { Tabs } from "./components/Tabs/Tabs";
import { TabsProps } from "./components/Tabs/Tabs.schema";
import { TabPanel, TabPanelProps } from "./components/TabPanel/TabPanel";
import { Accordion } from "./components/Accordion/Accordion";
import { AccordionProps } from "./components/Accordion/Accordion.schema";
import { AccordionPanel } from "./components/Accordion/AccordionPanel";

// Overlays
import { Dialog } from "./components/Dialog/Dialog";
import { DialogProps } from "./components/Dialog/Dialog.schema";

// Static / display
import { Card } from "./components/Card/Card";
import { CardProps } from "./components/Card/Card.schema";
import { MetricTile } from "./components/MetricTile/MetricTile";
import { MetricTileProps } from "./components/MetricTile/MetricTile.schema";
import { Avatar } from "./components/Avatar/Avatar";
import { AvatarProps } from "./components/Avatar/Avatar.schema";
import { Badge } from "./components/Badge/Badge";
import { BadgeProps } from "./components/Badge/Badge.schema";
import { KeyValueList } from "./components/KeyValueList/KeyValueList";
import { KeyValueListProps } from "./components/KeyValueList/KeyValueList.schema";
import { Heading } from "./components/Heading/Heading";
import { HeadingProps } from "./components/Heading/Heading.schema";
import { FeatureCard } from "./components/FeatureCard/FeatureCard";
import { FeatureCardProps } from "./components/FeatureCard/FeatureCard.schema";
import { Skeleton } from "./components/Skeleton/Skeleton";
import { SkeletonProps } from "./components/Skeleton/Skeleton.schema";
import { Divider } from "./components/Divider/Divider";
import { DividerProps } from "./components/Divider/Divider.schema";
import { Breadcrumb } from "./components/Breadcrumb/Breadcrumb";
import { BreadcrumbProps } from "./components/Breadcrumb/Breadcrumb.schema";
import { Alert } from "./components/Alert/Alert";
import { AlertProps } from "./components/Alert/Alert.schema";
import { EmptyState } from "./components/EmptyState/EmptyState";
import { EmptyStateProps } from "./components/EmptyState/EmptyState.schema";
// Spec C Slice 7 — interaction depth
import { BulkActionBar } from "./components/BulkActionBar/BulkActionBar";
import { BulkActionBarProps } from "./components/BulkActionBar/BulkActionBar.schema";
import { SavedViewsPicker } from "./components/SavedViewsPicker/SavedViewsPicker";
import { SavedViewsPickerProps } from "./components/SavedViewsPicker/SavedViewsPicker.schema";
import { GlobalSearch } from "./components/GlobalSearch/GlobalSearch";
import { GlobalSearchProps } from "./components/GlobalSearch/GlobalSearch.schema";
// SEARCH-3 — full-text search input + results panel.
import { SearchInput } from "./components/SearchInput/SearchInput";
import { SearchInputProps } from "./components/SearchInput/SearchInput.schema";
import { SearchResults } from "./components/SearchResults/SearchResults";
import { SearchResultsProps } from "./components/SearchResults/SearchResults.schema";
import { KeyboardShortcuts } from "./components/KeyboardShortcuts/KeyboardShortcuts";
import { KeyboardShortcutsProps } from "./components/KeyboardShortcuts/KeyboardShortcuts.schema";
// Spec C Slice 8 — dark-mode toggle
import { ThemeToggle } from "./components/ThemeToggle/ThemeToggle";
import { ThemeToggleProps } from "./components/ThemeToggle/ThemeToggle.schema";
// Spec C Slice 9 — illustrated empty state
import { IllustratedEmpty } from "./components/IllustratedEmpty/IllustratedEmpty";
import { IllustratedEmptyProps } from "./components/IllustratedEmpty/IllustratedEmpty.schema";
// Spec E Wave 2 — focus primitives
import { FocusTrap } from "./components/FocusTrap/FocusTrap";
import { FocusTrapProps } from "./components/FocusTrap/FocusTrap.schema";
import { SkipLink } from "./components/SkipLink/SkipLink";
import { SkipLinkProps } from "./components/SkipLink/SkipLink.schema";
import { FocusRing } from "./components/FocusRing/FocusRing";
import { FocusRingProps } from "./components/FocusRing/FocusRing.schema";
import { AutoFocus } from "./components/AutoFocus/AutoFocus";
import { AutoFocusProps } from "./components/AutoFocus/AutoFocus.schema";
import { LoadingState } from "./components/LoadingState/LoadingState";
import { LoadingStateProps } from "./components/LoadingState/LoadingState.schema";
// Spec E Wave 3 — advanced UX patterns
import { Wizard } from "./components/Wizard/Wizard";
import { WizardProps } from "./components/Wizard/Wizard.schema";
import { SplitView } from "./components/SplitView/SplitView";
import { SplitViewProps } from "./components/SplitView/SplitView.schema";
import { FilterBuilder } from "./components/FilterBuilder/FilterBuilder";
import { FilterBuilderProps } from "./components/FilterBuilder/FilterBuilder.schema";
import { TourOverlay } from "./components/TourOverlay/TourOverlay";
import { TourOverlayProps } from "./components/TourOverlay/TourOverlay.schema";
// Spec E Wave 1 — advanced interactions
import { UndoManager } from "./components/UndoManager/UndoManager";
import { UndoManagerProps } from "./components/UndoManager/UndoManager.schema";
import { PresenceIndicator } from "./components/PresenceIndicator/PresenceIndicator";
import { PresenceIndicatorProps } from "./components/PresenceIndicator/PresenceIndicator.schema";
import { OptimisticProvider } from "./components/OptimisticProvider/OptimisticProvider";
import { OptimisticProviderProps } from "./components/OptimisticProvider/OptimisticProvider.schema";

// Data
import { Table } from "./components/Table/Table";
import { TableSortable } from "./components/Table/TableSortable";
import { TableProps, TableSortableProps } from "./components/Table/Table.schema";
import { Chart } from "./components/Chart/Chart";
import { ChartProps as ChartPropsSchema } from "./components/Chart/Chart.schema";
import { Sparkline } from "./components/Sparkline/Sparkline";
import { SparklineProps as SparklinePropsSchema } from "./components/Sparkline/Sparkline.schema";
import { DataGrid } from "./components/DataGrid/DataGrid";
import { DataGridProps as DataGridPropsSchema } from "./components/DataGrid/DataGrid.schema";
import { EditableLineGrid } from "./components/EditableLineGrid/EditableLineGrid";
import { EditableLineGridProps as EditableLineGridPropsSchema } from "./components/EditableLineGrid/EditableLineGrid.schema";
import { Timeline } from "./components/Timeline/Timeline";
import { TimelineProps as TimelinePropsSchema } from "./components/Timeline/Timeline.schema";

// Tier 2 — enterprise batch 2
import { ApprovalStepper } from "./components/ApprovalStepper/ApprovalStepper";
import { ApprovalStepperProps as ApprovalStepperPropsSchema } from "./components/ApprovalStepper/ApprovalStepper.schema";
import { PersonCard } from "./components/PersonCard/PersonCard";
import { PersonCardProps as PersonCardPropsSchema } from "./components/PersonCard/PersonCard.schema";
import { FilterBar } from "./components/FilterBar/FilterBar";
import { FilterBarProps as FilterBarPropsSchema } from "./components/FilterBar/FilterBar.schema";
import { CommandPalette } from "./components/CommandPalette/CommandPalette";
import { CommandPaletteProps as CommandPalettePropsSchema } from "./components/CommandPalette/CommandPalette.schema";
import { ActivityFeed } from "./components/ActivityFeed/ActivityFeed";
import { ActivityFeedProps as ActivityFeedPropsSchema } from "./components/ActivityFeed/ActivityFeed.schema";

// Tier 2 — enterprise batch 3
import { EmptyStateRich } from "./components/EmptyStateRich/EmptyStateRich";
import { EmptyStateRichProps as EmptyStateRichPropsSchema } from "./components/EmptyStateRich/EmptyStateRich.schema";
import { DateRangePicker } from "./components/DateRangePicker/DateRangePicker";
import { DateRangePickerProps as DateRangePickerPropsSchema } from "./components/DateRangePicker/DateRangePicker.schema";
import { MultiSelect } from "./components/MultiSelect/MultiSelect";
import { MultiSelectProps as MultiSelectPropsSchema } from "./components/MultiSelect/MultiSelect.schema";

// Tier 2 Wave 4 — layout primitives
import { AppShell } from "./components/AppShell/AppShell";
import { AppShellProps as AppShellPropsSchema } from "./components/AppShell/AppShell.schema";
import { InspectorPanel } from "./components/InspectorPanel/InspectorPanel";
import { InspectorPanelProps as InspectorPanelPropsSchema } from "./components/InspectorPanel/InspectorPanel.schema";
import { TabPanelWithDeepLink } from "./components/TabPanelWithDeepLink/TabPanelWithDeepLink";
import { TabPanelWithDeepLinkProps as TabPanelWithDeepLinkPropsSchema } from "./components/TabPanelWithDeepLink/TabPanelWithDeepLink.schema";

// Form
import { Form } from "./components/Form/Form";
import { FormProps } from "./components/Form/Form.schema";
import { Input } from "./components/Input/Input";
import { InputProps } from "./components/Input/Input.schema";
import { Select } from "./components/Select/Select";
import { SelectProps } from "./components/Select/Select.schema";
import { Textarea } from "./components/Textarea/Textarea";
import { TextareaProps } from "./components/Textarea/Textarea.schema";
import { Checkbox } from "./components/Checkbox/Checkbox";
import { CheckboxProps } from "./components/Checkbox/Checkbox.schema";
import { DatePicker } from "./components/DatePicker/DatePicker";
import { DatePickerProps } from "./components/DatePicker/DatePicker.schema";

// Motion
import { FadeIn } from "./components/FadeIn/FadeIn";
import { FadeInProps } from "./components/FadeIn/FadeIn.schema";
import { Stagger } from "./components/Stagger/Stagger";
import { StaggerProps } from "./components/Stagger/Stagger.schema";

// ── Waves 1–6 — component additions (form inputs, overlays, feedback,
// data display, heavy composites, device/capture). Imported here so the
// runtime Registry can dispatch them; the schema union + starterRegistry
// already list them. ────────────────────────────────────────────────────
// Wave 1 — form inputs
import { Switch } from "./components/Switch/Switch";
import { SwitchProps } from "./components/Switch/Switch.schema";
import { NumberInput } from "./components/NumberInput/NumberInput";
import { NumberInputProps } from "./components/NumberInput/NumberInput.schema";
import { MoneyInput, MoneyDisplay } from "./components/Money/Money";
import { MoneyInputProps, MoneyDisplayProps } from "./components/Money/Money.schema";
import { RadioGroup } from "./components/RadioGroup/RadioGroup";
import { RadioGroupProps } from "./components/RadioGroup/RadioGroup.schema";
import { Slider } from "./components/Slider/Slider";
import { SliderProps } from "./components/Slider/Slider.schema";
import { FileUpload } from "./components/FileUpload/FileUpload";
import { FileUploadProps } from "./components/FileUpload/FileUpload.schema";
import { AddToCart } from "./components/AddToCart/AddToCart";
import { AddToCartProps } from "./components/AddToCart/AddToCart.schema";
import { CartBadge } from "./components/CartBadge/CartBadge";
import { CartBadgeProps } from "./components/CartBadge/CartBadge.schema";
import { CartPanel } from "./components/CartPanel/CartPanel";
import { CartPanelProps } from "./components/CartPanel/CartPanel.schema";
import { CartPage } from "./components/CartPage/CartPage";
import { CartPageProps } from "./components/CartPage/CartPage.schema";
import { Combobox } from "./components/Combobox/Combobox";
import { ComboboxProps } from "./components/Combobox/Combobox.schema";
// Wave 2 — overlays
import { DropdownMenu } from "./components/DropdownMenu/DropdownMenu";
import { DropdownMenuProps } from "./components/DropdownMenu/DropdownMenu.schema";
import { MobileNav } from "./components/MobileNav/MobileNav";
import { MobileNavProps } from "./components/MobileNav/MobileNav.schema";
import { Popover } from "./components/Popover/Popover";
import { PopoverProps } from "./components/Popover/Popover.schema";
import { Tooltip } from "./components/Tooltip/Tooltip";
import { TooltipProps } from "./components/Tooltip/Tooltip.schema";
import { Drawer } from "./components/Drawer/Drawer";
import { DrawerProps } from "./components/Drawer/Drawer.schema";
import { ContextMenu } from "./components/ContextMenu/ContextMenu";
import { ContextMenuProps } from "./components/ContextMenu/ContextMenu.schema";
import { HoverCard } from "./components/HoverCard/HoverCard";
import { HoverCardProps } from "./components/HoverCard/HoverCard.schema";
import { Menubar } from "./components/Menubar/Menubar";
import { MenubarProps } from "./components/Menubar/Menubar.schema";
// Wave 3 — feedback + inputs
import { Progress } from "./components/Progress/Progress";
import { ProgressProps } from "./components/Progress/Progress.schema";
import { Spinner } from "./components/Spinner/Spinner";
import { SpinnerProps } from "./components/Spinner/Spinner.schema";
import { Redirect } from "./components/Redirect/Redirect";
import { RedirectProps } from "./components/Redirect/Redirect.schema";
import { Banner } from "./components/Banner/Banner";
import { BannerProps } from "./components/Banner/Banner.schema";
import { TimePicker } from "./components/TimePicker/TimePicker";
import { TimePickerProps } from "./components/TimePicker/TimePicker.schema";
import { ColorPicker } from "./components/ColorPicker/ColorPicker";
import { ColorPickerProps } from "./components/ColorPicker/ColorPicker.schema";
import { InputOTP } from "./components/InputOTP/InputOTP";
import { InputOTPProps } from "./components/InputOTP/InputOTP.schema";
import { Rating } from "./components/Rating/Rating";
import { RatingProps } from "./components/Rating/Rating.schema";
import { MaskedInput } from "./components/MaskedInput/MaskedInput";
import { MaskedInputProps } from "./components/MaskedInput/MaskedInput.schema";
import { KeyValueInput } from "./components/KeyValueInput/KeyValueInput";
import { KeyValueInputProps } from "./components/KeyValueInput/KeyValueInput.schema";
// Enterprise visualisation gap-fill (Gauge / Heatmap / Schematic / Stepper)
import { Gauge } from "./components/Gauge/Gauge";
import { GaugeProps } from "./components/Gauge/Gauge.schema";
import { SplitArc } from "./components/SplitArc/SplitArc";
import { SplitArcProps } from "./components/SplitArc/SplitArc.schema";
import { Heatmap } from "./components/Heatmap/Heatmap";
import { HeatmapProps } from "./components/Heatmap/Heatmap.schema";
import { Schematic } from "./components/Schematic/Schematic";
import { SchematicProps } from "./components/Schematic/Schematic.schema";
import { Stepper } from "./components/Stepper/Stepper";
import { StepperProps } from "./components/Stepper/Stepper.schema";
// Wave 4 — data display
import { Tag } from "./components/Tag/Tag";
import { TagProps } from "./components/Tag/Tag.schema";
import { Stat } from "./components/Stat/Stat";
import { StatProps } from "./components/Stat/Stat.schema";
import { SideNav } from "./components/SideNav/SideNav";
import { SideNavProps } from "./components/SideNav/SideNav.schema";
import { DescriptionList } from "./components/DescriptionList/DescriptionList";
import { DescriptionListProps } from "./components/DescriptionList/DescriptionList.schema";
import { List } from "./components/List/List";
import { ListProps } from "./components/List/List.schema";
import { SegmentedControl } from "./components/SegmentedControl/SegmentedControl";
import { SegmentedControlProps } from "./components/SegmentedControl/SegmentedControl.schema";
import { Tree } from "./components/Tree/Tree";
import { TreeProps } from "./components/Tree/Tree.schema";
import { Transfer } from "./components/Transfer/Transfer";
import { TransferProps } from "./components/Transfer/Transfer.schema";
import { Cascader } from "./components/Cascader/Cascader";
import { CascaderProps } from "./components/Cascader/Cascader.schema";
// Wave 5 — heavy composites
import { Calendar } from "./components/Calendar/Calendar";
import { CalendarProps } from "./components/Calendar/Calendar.schema";
import { Kanban } from "./components/Kanban/Kanban";
import { KanbanProps } from "./components/Kanban/Kanban.schema";
import { ResourceTimeline } from "./components/ResourceTimeline/ResourceTimeline";
import { ResourceTimelineProps } from "./components/ResourceTimeline/ResourceTimeline.schema";
import { RichTextEditor } from "./components/RichTextEditor/RichTextEditor";
import { RichTextEditorProps } from "./components/RichTextEditor/RichTextEditor.schema";
import { Carousel } from "./components/Carousel/Carousel";
import { CarouselProps } from "./components/Carousel/Carousel.schema";
import { Lightbox } from "./components/Lightbox/Lightbox";
import { LightboxProps } from "./components/Lightbox/Lightbox.schema";
import { CodeBlock } from "./components/CodeBlock/CodeBlock";
import { CodeBlockProps } from "./components/CodeBlock/CodeBlock.schema";
import { CustomBlock } from "./components/CustomBlock/CustomBlock";
import { CustomBlockProps } from "./components/CustomBlock/CustomBlock.schema";
import { QRCode } from "./components/QRCode/QRCode";
import { QRCodeProps } from "./components/QRCode/QRCode.schema";
// Wave 6 — device & capture
import { BarcodeScanner } from "./components/BarcodeScanner/BarcodeScanner";
import { BarcodeScannerProps } from "./components/BarcodeScanner/BarcodeScanner.schema";
import { CameraCapture } from "./components/CameraCapture/CameraCapture";
import { CameraCaptureProps } from "./components/CameraCapture/CameraCapture.schema";
import { Scanner } from "./components/Scanner/Scanner";
import { ScannerProps } from "./components/Scanner/Scanner.schema";
import { ValidationChecklist } from "./components/ValidationChecklist/ValidationChecklist";
import { ValidationChecklistProps } from "./components/ValidationChecklist/ValidationChecklist.schema";

// Composition Recipe Library — v1 anchors (member_home).
// Anchors are typed slots that composition recipes cite by name; they
// consume design tokens only and never hard-code color/type/spacing.
// Backend authority: backend/services/composition/anchors.json.
import { PinnedMomentHero, PinnedMomentHeroProps } from "./anchors/PinnedMomentHero/PinnedMomentHero";
import { VitalsInContext, VitalsInContextProps } from "./anchors/VitalsInContext/VitalsInContext";
import { ScanStrip, ScanStripProps } from "./anchors/ScanStrip/ScanStrip";
import { RecsRailReasoned, RecsRailReasonedProps } from "./anchors/RecsRailReasoned/RecsRailReasoned";
import { CommunityPulse, CommunityPulseProps } from "./anchors/CommunityPulse/CommunityPulse";
import { StickyPrimaryCta, StickyPrimaryCtaProps } from "./anchors/StickyPrimaryCta/StickyPrimaryCta";
// shopper_home v1 anchors.
import { FeaturedMomentHero, FeaturedMomentHeroProps } from "./anchors/FeaturedMomentHero/FeaturedMomentHero";
import { ReasonsToReturnRow, ReasonsToReturnRowProps } from "./anchors/ReasonsToReturnRow/ReasonsToReturnRow";
import { TrendingRail, TrendingRailProps } from "./anchors/TrendingRail/TrendingRail";
import { TasteRecsRail, TasteRecsRailProps } from "./anchors/TasteRecsRail/TasteRecsRail";
import { BrandStoryPulse, BrandStoryPulseProps } from "./anchors/BrandStoryPulse/BrandStoryPulse";
import { CartCta, CartCtaProps } from "./anchors/CartCta/CartCta";
// operator_console v1 anchors.
import { AttentionQueueHero, AttentionQueueHeroProps } from "./anchors/AttentionQueueHero/AttentionQueueHero";
import { SlaVitalsStrip, SlaVitalsStripProps } from "./anchors/SlaVitalsStrip/SlaVitalsStrip";
import { LiveEventLog, LiveEventLogProps } from "./anchors/LiveEventLog/LiveEventLog";
import { TeamStatusBoard, TeamStatusBoardProps } from "./anchors/TeamStatusBoard/TeamStatusBoard";
import { ShiftMetricsRail, ShiftMetricsRailProps } from "./anchors/ShiftMetricsRail/ShiftMetricsRail";
import { EmergencyActionRail, EmergencyActionRailProps } from "./anchors/EmergencyActionRail/EmergencyActionRail";
// manager_overview v1 anchors.
import { TeamGlanceHero, TeamGlanceHeroProps } from "./anchors/TeamGlanceHero/TeamGlanceHero";
import { PrioritiesStrip, PrioritiesStripProps } from "./anchors/PrioritiesStrip/PrioritiesStrip";
import { CalendarWeek, CalendarWeekProps } from "./anchors/CalendarWeek/CalendarWeek";
import { EscalationsQueue, EscalationsQueueProps } from "./anchors/EscalationsQueue/EscalationsQueue";
import { RecognitionFeed, RecognitionFeedProps } from "./anchors/RecognitionFeed/RecognitionFeed";
// creator/field/learner/analyst/patron v1 anchors — 5 new components +
// remaining anchor slots re-use existing components via anchors.json mapping.
import { DiscoveryRail, DiscoveryRailProps } from "./anchors/DiscoveryRail/DiscoveryRail";
import { DraftFocusHero, DraftFocusHeroProps } from "./anchors/DraftFocusHero/DraftFocusHero";
import { JobChecklist, JobChecklistProps } from "./anchors/JobChecklist/JobChecklist";
import { CompletionCapture, CompletionCaptureProps } from "./anchors/CompletionCapture/CompletionCapture";
import { NarrativeHeadline, NarrativeHeadlineProps } from "./anchors/NarrativeHeadline/NarrativeHeadline";

// Register-keyed variant selector
import { selectVariant } from "./components/variants";
import type { RegisterName } from "./theme/registers";

// AccordionPanel schema comes from the schema package
import { AccordionPanelNode } from "@tentoroforge/schema";

/**
 * Build a default-prop-injecting wrapper. When `defaults` is non-empty,
 * the returned component spreads `defaults` first, then `p` — caller-provided
 * props always win, but absent props fall through to the injected defaults.
 */
function withDefaults<P extends Record<string, unknown>>(
  Component: React.ComponentType<P>,
  defaults: Partial<P>,
): React.ComponentType<P> {
  const Wrapped = (props: P) => {
    const merged = { ...defaults, ...props } as P;
    return <Component {...merged} />;
  };
  Wrapped.displayName = `WithDefaults(${Component.displayName ?? Component.name ?? "Component"})`;
  return Wrapped;
}

export interface BuildDefaultRegistryOptions {
  /** Design register name (default: "default"). */
  register?: string;
  /**
   * Base URL for illustration slugs.
   * When provided, Hero / Section / EmptyStateRich will resolve illustration
   * slugs against this path.  Omit (or pass undefined) to let the components
   * use their own default (/illustrations).
   */
  illustrationBasePath?: string;
}

/**
 * Build a fully-populated Registry with all default library components.
 *
 * @param opts - Optional configuration (register name, illustration base path).
 * @returns A Registry instance ready to be passed to renderNode().
 */
/**
 * Containers whose children carry meaning beyond their order.
 *
 * Everything absent from this table takes a homogeneous body. Keep it that
 * way: a positional contract that is not declared here is one a generated
 * page can get wrong silently.
 */
const CHILD_CONTRACTS: Record<string, ChildContract> = {
  // children[0] is the list, children[1] is the detail pane.
  SplitView: { kind: "roles", roles: ["master", "detail"] },
  // One panel per entry in the `tabs` prop, in the same order.
  Tabs: { kind: "repeat", role: "panel", pairedWith: "tabs" },
  // Each child is an AccordionPanel carrying its own label.
  Accordion: { kind: "repeat", role: "panel" },
  Sidebar: { kind: "repeat", role: "item" },
};

export function buildDefaultRegistry(opts: BuildDefaultRegistryOptions = {}): Registry {
  const register = opts.register ?? "default";
  const illustrationBasePath = opts.illustrationBasePath;
  const illustrationDefaults = illustrationBasePath
    ? { __illustrationBasePath: illustrationBasePath }
    : {};

  const registry = createRegistry();

  const reg = (
    name: string,
    component: React.ComponentType<any>,
    propsSchema: import("zod").ZodSchema<any>,
    category: LibraryCategory,
    acceptsChildren = false,
  ) =>
    registry.register({
      name, component, propsSchema, category, acceptsChildren,
      ...(CHILD_CONTRACTS[name] ? { childContract: CHILD_CONTRACTS[name] } : {}),
    });

  // Interactive
  reg("Button", Button, ButtonProps, "interactive");
  reg("Link", Link, LinkProps, "interactive");
  reg("NavLink", NavLink, NavLinkProps, "navigation");
  reg("IconButton", IconButton, IconButtonProps, "interactive");

  // Layout — Hero uses a register-keyed variant
  const HeroVariant = selectVariant("Hero", register as RegisterName);
  const HeroWithBase = withDefaults(HeroVariant as React.ComponentType<any>, illustrationDefaults);
  const SectionWithBase = withDefaults(Section as React.ComponentType<any>, illustrationDefaults);
  reg("Hero", HeroWithBase, HeroProps, "layout", true);
  reg("Section", SectionWithBase, SectionProps, "layout", true);
  reg("Split", Split, SplitProps, "layout", true);
  reg("Sidebar", Sidebar, SidebarProps, "layout", true);
  reg("Cluster", Cluster, ClusterProps, "layout", true);
  reg("Tabs", Tabs, TabsProps, "layout", true);
  reg("TabPanel", TabPanel, TabPanelProps, "layout", true);
  reg("Accordion", Accordion, AccordionProps, "layout", true);
  // AccordionPanel has no separate library Zod schema — derive from schema pkg
  reg("AccordionPanel", AccordionPanel, AccordionPanelNode.shape.props, "layout", true);

  // Static / display — Card and MetricTile use register-keyed variants
  const CardVariant = selectVariant("Card", register as RegisterName);
  const MetricTileVariant = selectVariant("MetricTile", register as RegisterName);
  reg("Card", CardVariant, CardProps, "static", true);
  reg("MetricTile", MetricTileVariant, MetricTileProps, "static");
  reg("Avatar", Avatar, AvatarProps, "static");
  reg("Badge", Badge, BadgeProps, "static");
  reg("KeyValueList", KeyValueList, KeyValueListProps, "static");
  reg("Heading", Heading, HeadingProps, "static");
  reg("FeatureCard", FeatureCard, FeatureCardProps, "static");
  reg("Skeleton", Skeleton, SkeletonProps, "feedback");
  reg("Divider", Divider, DividerProps, "static");
  reg("Breadcrumb", Breadcrumb, BreadcrumbProps, "navigation");
  reg("Alert", Alert, AlertProps, "feedback");
  reg("EmptyState", EmptyState, EmptyStateProps, "feedback");
  // Spec C Slice 7 — interaction depth
  reg("BulkActionBar", BulkActionBar, BulkActionBarProps, "interactive");
  reg("SavedViewsPicker", SavedViewsPicker, SavedViewsPickerProps, "interactive");
  reg("GlobalSearch", GlobalSearch, GlobalSearchProps, "interactive");
  // SEARCH-3 — op:"search"-backed search input + results pair.
  reg("SearchInput", SearchInput, SearchInputProps, "interactive");
  reg("SearchResults", SearchResults, SearchResultsProps, "data");
  reg("KeyboardShortcuts", KeyboardShortcuts, KeyboardShortcutsProps, "interactive");
  // Spec C Slice 8 — dark-mode toggle
  reg("ThemeToggle", ThemeToggle, ThemeToggleProps, "interactive");
  // Spec C Slice 9 — illustrated empty state
  reg("IllustratedEmpty", IllustratedEmpty, IllustratedEmptyProps, "feedback");
  reg("LoadingState", LoadingState, LoadingStateProps, "feedback");
  // Spec E Wave 2 — focus primitives (accessibility spine).
  // Registered as "feedback" for lack of a better category; not surfaced
  // in visual pickers but wired for schema-authored use.
  reg("FocusTrap", FocusTrap, FocusTrapProps, "feedback", true);
  reg("SkipLink",  SkipLink,  SkipLinkProps,  "feedback");
  reg("FocusRing", FocusRing, FocusRingProps, "feedback", true);
  reg("AutoFocus", AutoFocus, AutoFocusProps, "feedback", true);
  // Spec E Wave 1 — advanced interactions (undo/presence/optimistic).
  reg("UndoManager",        UndoManager,        UndoManagerProps,        "feedback");
  reg("PresenceIndicator",  PresenceIndicator,  PresenceIndicatorProps,  "feedback");
  reg("OptimisticProvider", OptimisticProvider, OptimisticProviderProps, "feedback", true);
  // Spec E Wave 3 — advanced UX patterns (wizard/split/filter/tour).
  reg("Wizard",        Wizard,        WizardProps,        "form");
  reg("SplitView",     SplitView,     SplitViewProps,     "layout", true);
  reg("FilterBuilder", FilterBuilder, FilterBuilderProps, "navigation");
  reg("TourOverlay",   TourOverlay,   TourOverlayProps,   "feedback");

  // Data
  reg("Table", Table, TableProps, "data");
  reg("TableSortable", TableSortable, TableSortableProps, "data");
  reg("Chart",     Chart,     ChartPropsSchema,     "data");
  reg("Sparkline", Sparkline, SparklinePropsSchema, "data");
  reg("DataGrid",  DataGrid,  DataGridPropsSchema,  "data");
  reg("EditableLineGrid", EditableLineGrid, EditableLineGridPropsSchema, "data");
  reg("Timeline",  Timeline,  TimelinePropsSchema,  "data");

  // Tier 2 — enterprise batch 2
  reg("ApprovalStepper", ApprovalStepper, ApprovalStepperPropsSchema, "data");
  reg("PersonCard",      PersonCard,      PersonCardPropsSchema,      "static");
  reg("FilterBar",       FilterBar,       FilterBarPropsSchema,       "navigation");
  reg("CommandPalette",  CommandPalette,  CommandPalettePropsSchema,  "navigation");
  reg("ActivityFeed",    ActivityFeed,    ActivityFeedPropsSchema,    "data");

  // Tier 2 — enterprise batch 3
  const EmptyStateRichWithBase = withDefaults(EmptyStateRich as React.ComponentType<any>, illustrationDefaults);
  reg("EmptyStateRich",  EmptyStateRichWithBase,  EmptyStateRichPropsSchema,  "feedback");
  reg("DateRangePicker", DateRangePicker, DateRangePickerPropsSchema, "form");
  reg("MultiSelect",     MultiSelect,     MultiSelectPropsSchema,     "form");

  // Tier 2 Wave 4 — layout primitives
  reg("AppShell",             AppShell,             AppShellPropsSchema,             "layout", true);
  reg("InspectorPanel",       InspectorPanel,       InspectorPanelPropsSchema,       "layout", true);
  reg("TabPanelWithDeepLink", TabPanelWithDeepLink, TabPanelWithDeepLinkPropsSchema, "layout", true);

  // Form
  reg("Form",       Form,       FormProps,       "form", true);
  reg("Input",      Input,      InputProps,      "form");
  reg("Select",     Select,     SelectProps,     "form");
  reg("Textarea",   Textarea,   TextareaProps,   "form");
  reg("Checkbox",   Checkbox,   CheckboxProps,   "form");
  reg("DatePicker", DatePicker, DatePickerProps, "form");

  // Motion
  reg("FadeIn",  FadeIn,  FadeInProps,  "motion", true);
  reg("Stagger", Stagger, StaggerProps, "motion", true);

  // Overlays
  reg("Dialog", Dialog, DialogProps, "static", true);

  // ── Waves 1–6 — additions ─────────────────────────────────────────────
  // Wave 1 — form inputs
  reg("Switch",      Switch,      SwitchProps,      "form");
  reg("NumberInput", NumberInput, NumberInputProps, "form");
  // Money: first-class banking money control + read-only formatter. Amount is
  // a decimal string (never a JS number), currency is a 3-letter ISO code.
  reg("MoneyInput",   MoneyInput,   MoneyInputProps,   "form");
  reg("MoneyDisplay", MoneyDisplay, MoneyDisplayProps, "static");
  reg("RadioGroup",  RadioGroup,  RadioGroupProps,  "form");
  reg("Slider",      Slider,      SliderProps,      "form");
  reg("FileUpload",  FileUpload,  FileUploadProps,  "form");
  reg("Combobox",    Combobox,    ComboboxProps,    "form");
  // Wave 2 — overlays
  reg("DropdownMenu", DropdownMenu, DropdownMenuProps, "navigation");
  reg("MobileNav",    MobileNav,    MobileNavProps,    "navigation");
  reg("Popover",      Popover,      PopoverProps,      "static");
  reg("Tooltip",      Tooltip,      TooltipProps,      "feedback");
  reg("Drawer",       Drawer,       DrawerProps,       "static");
  reg("ContextMenu",  ContextMenu,  ContextMenuProps,  "navigation");
  reg("HoverCard",    HoverCard,    HoverCardProps,    "static");
  reg("Menubar",      Menubar,      MenubarProps,      "navigation");
  // Wave 3 — feedback + inputs
  reg("Progress",    Progress,    ProgressProps,    "feedback");
  reg("Spinner",     Spinner,     SpinnerProps,     "feedback");
  reg("Redirect",    Redirect,    RedirectProps,    "navigation");
  reg("Banner",      Banner,      BannerProps,      "feedback");
  reg("TimePicker",  TimePicker,  TimePickerProps,  "form");
  reg("ColorPicker", ColorPicker, ColorPickerProps, "form");
  reg("InputOTP",    InputOTP,    InputOTPProps,    "form");
  reg("Rating",      Rating,      RatingProps,      "form");
  reg("MaskedInput", MaskedInput, MaskedInputProps, "form");
  reg("KeyValueInput", KeyValueInput, KeyValueInputProps, "form");
  // Enterprise visualisation gap-fill
  reg("Gauge",     Gauge,     GaugeProps,     "static");
  reg("SplitArc",  SplitArc,  SplitArcProps,  "static");
  reg("Heatmap",   Heatmap,   HeatmapProps,   "static");
  reg("Schematic", Schematic, SchematicProps, "static");
  reg("Stepper",   Stepper,   StepperProps,   "static");
  // Wave 4 — data display
  reg("Tag",              Tag,              TagProps,              "static");
  reg("Stat",             Stat,             StatProps,             "data");
  reg("SideNav",          SideNav,          SideNavProps,          "navigation");
  reg("DescriptionList",  DescriptionList,  DescriptionListProps,  "static");
  reg("List",             List,             ListProps,             "data");
  reg("SegmentedControl", SegmentedControl, SegmentedControlProps, "form");
  reg("Tree",             Tree,             TreeProps,             "data");
  reg("Transfer",         Transfer,         TransferProps,         "form");
  reg("Cascader",         Cascader,         CascaderProps,         "form");
  // Wave 5 — heavy composites
  reg("Calendar",       Calendar,       CalendarProps,       "form");
  reg("Kanban",         Kanban,         KanbanProps,         "data");
  reg("ResourceTimeline", ResourceTimeline, ResourceTimelineProps, "data");
  reg("RichTextEditor", RichTextEditor, RichTextEditorProps, "form");
  reg("Carousel",       Carousel,       CarouselProps,       "static");
  reg("Lightbox",       Lightbox,       LightboxProps,       "static");
  reg("CodeBlock",      CodeBlock,      CodeBlockProps,      "static");
  reg("CustomBlock",    CustomBlock,    CustomBlockProps,    "static");
  reg("QRCode",         QRCode,         QRCodeProps,         "static");
  // Wave 6 — device & capture
  reg("BarcodeScanner",      BarcodeScanner,      BarcodeScannerProps,      "form");
  reg("CameraCapture",       CameraCapture,       CameraCaptureProps,       "form");
  reg("Scanner",             Scanner,             ScannerProps,             "form");
  reg("ValidationChecklist", ValidationChecklist, ValidationChecklistProps, "data");

  // Commerce — cart runtime primitives. Storage + API live in the runtime
  // (forge_cart table + /api/cart routes); these components are the UI surface.
  reg("AddToCart", AddToCart, AddToCartProps, "interactive");
  reg("CartBadge", CartBadge, CartBadgeProps, "navigation");
  reg("CartPanel", CartPanel, CartPanelProps, "data");
  reg("CartPage",  CartPage,  CartPageProps,  "static");

  // Composition Recipe Library — v1 anchors (see anchors.json).
  // Each anchor is a typed slot; recipes cite them by name and the deterministic
  // page builder resolves anchor → registered component here.
  reg("PinnedMomentHero", PinnedMomentHero, PinnedMomentHeroProps, "layout");
  reg("VitalsInContext",  VitalsInContext,  VitalsInContextProps,  "data");
  reg("ScanStrip",        ScanStrip,        ScanStripProps,        "navigation");
  reg("RecsRailReasoned", RecsRailReasoned, RecsRailReasonedProps, "data");
  reg("CommunityPulse",   CommunityPulse,   CommunityPulseProps,   "data");
  reg("StickyPrimaryCta", StickyPrimaryCta, StickyPrimaryCtaProps, "interactive");
  // shopper_home v1
  reg("FeaturedMomentHero", FeaturedMomentHero, FeaturedMomentHeroProps, "layout");
  reg("ReasonsToReturnRow", ReasonsToReturnRow, ReasonsToReturnRowProps, "static");
  reg("TrendingRail",       TrendingRail,       TrendingRailProps,       "data");
  reg("TasteRecsRail",      TasteRecsRail,      TasteRecsRailProps,      "data");
  reg("BrandStoryPulse",    BrandStoryPulse,    BrandStoryPulseProps,    "layout");
  reg("CartCta",            CartCta,            CartCtaProps,            "interactive");
  // operator_console v1
  reg("AttentionQueueHero",  AttentionQueueHero,  AttentionQueueHeroProps,  "data");
  reg("SlaVitalsStrip",      SlaVitalsStrip,      SlaVitalsStripProps,      "data");
  reg("LiveEventLog",        LiveEventLog,        LiveEventLogProps,        "data");
  reg("TeamStatusBoard",     TeamStatusBoard,     TeamStatusBoardProps,     "data");
  reg("ShiftMetricsRail",    ShiftMetricsRail,    ShiftMetricsRailProps,    "data");
  reg("EmergencyActionRail", EmergencyActionRail, EmergencyActionRailProps, "interactive");
  // manager_overview v1
  reg("TeamGlanceHero",   TeamGlanceHero,   TeamGlanceHeroProps,   "layout");
  reg("PrioritiesStrip",  PrioritiesStrip,  PrioritiesStripProps,  "data");
  reg("CalendarWeek",     CalendarWeek,     CalendarWeekProps,     "data");
  reg("EscalationsQueue", EscalationsQueue, EscalationsQueueProps, "data");
  reg("RecognitionFeed",  RecognitionFeed,  RecognitionFeedProps,  "data");
  // creator/field/learner/analyst/patron v1 (5 new components)
  reg("DiscoveryRail",     DiscoveryRail,     DiscoveryRailProps,     "navigation");
  reg("DraftFocusHero",    DraftFocusHero,    DraftFocusHeroProps,    "layout");
  reg("JobChecklist",      JobChecklist,      JobChecklistProps,      "data");
  reg("CompletionCapture", CompletionCapture, CompletionCaptureProps, "form");
  reg("NarrativeHeadline", NarrativeHeadline, NarrativeHeadlineProps, "layout");

  return registry;
}
