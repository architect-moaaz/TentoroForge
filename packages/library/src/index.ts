// Spec E Wave 2 — accessibility infrastructure (LiveRegion + announce()).
export {
  LiveRegion,
  announce,
  subscribe as subscribeToAnnouncements,
  __resetAnnouncerForTests,
} from "./a11y";
export type { LiveUrgency, LiveRegionProps } from "./a11y";

// Spec E Wave 2 — focus primitives (used by Dialog/Drawer/Popover
// shells + auto-injected into generated app roots).
export { FocusTrap } from "./components/FocusTrap/FocusTrap";
export type { FocusTrapProps } from "./components/FocusTrap/FocusTrap";
export { FocusTrapProps as FocusTrapPropsSchema } from "./components/FocusTrap/FocusTrap.schema";
export type { FocusTrapPropsType } from "./components/FocusTrap/FocusTrap.schema";

export { SkipLink } from "./components/SkipLink/SkipLink";
export type { SkipLinkProps } from "./components/SkipLink/SkipLink";
export { SkipLinkProps as SkipLinkPropsSchema } from "./components/SkipLink/SkipLink.schema";
export type { SkipLinkPropsType } from "./components/SkipLink/SkipLink.schema";

export { FocusRing } from "./components/FocusRing/FocusRing";
export type { FocusRingProps } from "./components/FocusRing/FocusRing";
export { FocusRingProps as FocusRingPropsSchema } from "./components/FocusRing/FocusRing.schema";
export type { FocusRingPropsType } from "./components/FocusRing/FocusRing.schema";

export { AutoFocus } from "./components/AutoFocus/AutoFocus";
export type { AutoFocusProps } from "./components/AutoFocus/AutoFocus";
export { AutoFocusProps as AutoFocusPropsSchema } from "./components/AutoFocus/AutoFocus.schema";
export type { AutoFocusPropsType } from "./components/AutoFocus/AutoFocus.schema";

export { defaultTokens } from "./theme/default-tokens";
export type { TokenGroups } from "./theme/default-tokens";
export * from "./theme/registers";
export type {
  RadiusScale,
  Density,
  Elevation,
  Motion,
  ScaleMode,
  TypographyDisplay,
  TypographyBodyText,
  TypographyNumeric,
  ExpandedTokens,
} from "./theme/token-types";
export {
  TokensProvider,
  useTokens,
  useDensity,
  useElevation,
  useMotionLevel,
  useRadiusScale,
} from "./theme/tokens-context";

export * from "./types/hierarchy";
export { createRegistry } from "./registry";
export type { Registry, LibraryEntry, LibraryCategory } from "./registry";
export { buildDefaultRegistry } from "./buildDefaultRegistry";
export type { BuildDefaultRegistryOptions } from "./buildDefaultRegistry";
export { Box, Text, Image } from "./primitives/index";
export { layouts } from "./layouts/index";

// Interactive components
export { Button } from "./components/Button/Button";
export { ButtonProps } from "./components/Button/Button.schema";
export type { ButtonPropsType } from "./components/Button/Button.schema";

export { IconButton } from "./components/IconButton/IconButton";
export { IconButtonProps } from "./components/IconButton/IconButton.schema";
export type { IconButtonPropsType } from "./components/IconButton/IconButton.schema";

export { Link } from "./components/Link/Link";
export { LinkProps } from "./components/Link/Link.schema";
export type { LinkPropsType } from "./components/Link/Link.schema";

// Form components
export { Form } from "./components/Form/Form";
export { FormProps } from "./components/Form/Form.schema";
export type { FormPropsType } from "./components/Form/Form.schema";

// Static components
export { Heading } from "./components/Heading/Heading";
export { HeadingProps } from "./components/Heading/Heading.schema";
export type { HeadingPropsType } from "./components/Heading/Heading.schema";

export { Badge } from "./components/Badge/Badge";
export { BadgeProps } from "./components/Badge/Badge.schema";
export type { BadgePropsType } from "./components/Badge/Badge.schema";

export { Divider } from "./components/Divider/Divider";
export { DividerProps } from "./components/Divider/Divider.schema";
export type { DividerPropsType } from "./components/Divider/Divider.schema";

export { Card } from "./components/Card/Card";
export { CardProps } from "./components/Card/Card.schema";
export type { CardPropsType } from "./components/Card/Card.schema";

export { OverlayCard } from "./components/OverlayCard/OverlayCard";
export type { OverlayCardProps } from "./components/OverlayCard/OverlayCard";
export { OverlayCardProps as OverlayCardPropsSchema } from "./components/OverlayCard/OverlayCard.schema";
export type { OverlayCardPropsType } from "./components/OverlayCard/OverlayCard.schema";

export { EmptyState } from "./components/EmptyState/EmptyState";
export { EmptyStateProps } from "./components/EmptyState/EmptyState.schema";
export type { EmptyStatePropsType } from "./components/EmptyState/EmptyState.schema";

export { LoadingState } from "./components/LoadingState/LoadingState";
export { LoadingStateProps } from "./components/LoadingState/LoadingState.schema";
export type { LoadingStatePropsType } from "./components/LoadingState/LoadingState.schema";

export { Pagination } from "./components/Pagination/Pagination";
export { PaginationProps } from "./components/Pagination/Pagination.schema";
export type { PaginationPropsType } from "./components/Pagination/Pagination.schema";

// Data display components
export { Table } from "./components/Table/Table";
export { TableSortable } from "./components/Table/TableSortable";
export { TableProps } from "./components/Table/Table.schema";
export type { TablePropsType, ColumnDef } from "./components/Table/Table.schema";

// Feedback components
export { Alert } from "./components/Alert/Alert";
export { AlertProps } from "./components/Alert/Alert.schema";
export type { AlertPropsType } from "./components/Alert/Alert.schema";

export { ToastProvider, useToast } from "./components/Toast/Toast";

export { ConfirmDialog } from "./components/ConfirmDialog/ConfirmDialog";
export { ConfirmDialogProps } from "./components/ConfirmDialog/ConfirmDialog.schema";
export type { ConfirmDialogPropsType } from "./components/ConfirmDialog/ConfirmDialog.schema";

export { Dialog } from "./components/Dialog/Dialog";
export { DialogProps } from "./components/Dialog/Dialog.schema";
export type { DialogPropsType } from "./components/Dialog/Dialog.schema";

export { DropdownMenu } from "./components/DropdownMenu/DropdownMenu";
export { DropdownMenuProps } from "./components/DropdownMenu/DropdownMenu.schema";
export type { DropdownMenuPropsType } from "./components/DropdownMenu/DropdownMenu.schema";

export { Popover } from "./components/Popover/Popover";
export { PopoverProps } from "./components/Popover/Popover.schema";
export type { PopoverPropsType } from "./components/Popover/Popover.schema";

export { Tooltip } from "./components/Tooltip/Tooltip";
export { TooltipProps } from "./components/Tooltip/Tooltip.schema";
export type { TooltipPropsType } from "./components/Tooltip/Tooltip.schema";

// Navigation components
export { NavLink } from "./components/NavLink/NavLink";
export { NavLinkProps } from "./components/NavLink/NavLink.schema";
export type { NavLinkPropsType } from "./components/NavLink/NavLink.schema";

export { Breadcrumb } from "./components/Breadcrumb/Breadcrumb";
export { BreadcrumbProps } from "./components/Breadcrumb/Breadcrumb.schema";
export type { BreadcrumbPropsType, BreadcrumbItem } from "./components/Breadcrumb/Breadcrumb.schema";

// Marketing / hero components
export { Hero } from "./components/Hero/Hero";
export { HeroProps } from "./components/Hero/Hero.schema";
export type { HeroPropsType } from "./components/Hero/Hero.schema";

export { Section } from "./components/Section/Section";
export { SectionProps } from "./components/Section/Section.schema";
export type { SectionPropsType } from "./components/Section/Section.schema";

export { MetricTile } from "./components/MetricTile/MetricTile";
export { MetricTileProps } from "./components/MetricTile/MetricTile.schema";
export type { MetricTilePropsType } from "./components/MetricTile/MetricTile.schema";

export { FeatureCard } from "./components/FeatureCard/FeatureCard";
export { FeatureCardProps } from "./components/FeatureCard/FeatureCard.schema";
export type { FeatureCardPropsType } from "./components/FeatureCard/FeatureCard.schema";

// Layout primitives
export { Split } from "./components/Split/Split";
export { SplitProps } from "./components/Split/Split.schema";
export type { SplitPropsType } from "./components/Split/Split.schema";

export { Sidebar } from "./components/Sidebar/Sidebar";
export { SidebarProps } from "./components/Sidebar/Sidebar.schema";
export type { SidebarPropsType } from "./components/Sidebar/Sidebar.schema";

export { Cluster } from "./components/Cluster/Cluster";
export { ClusterProps } from "./components/Cluster/Cluster.schema";
export type { ClusterPropsType } from "./components/Cluster/Cluster.schema";

// Interactive containers
export { Tabs } from "./components/Tabs/Tabs";
export { TabsProps } from "./components/Tabs/Tabs.schema";
export type { TabsPropsType } from "./components/Tabs/Tabs.schema";

export { Accordion } from "./components/Accordion/Accordion";
export { AccordionProps } from "./components/Accordion/Accordion.schema";
export type { AccordionPropsType } from "./components/Accordion/Accordion.schema";
export { AccordionPanel } from "./components/Accordion/AccordionPanel";

// Display components
export { Avatar } from "./components/Avatar/Avatar";
export { AvatarProps } from "./components/Avatar/Avatar.schema";
export type { AvatarPropsType } from "./components/Avatar/Avatar.schema";

export { KeyValueList } from "./components/KeyValueList/KeyValueList";
export { KeyValueListProps } from "./components/KeyValueList/KeyValueList.schema";
export type { KeyValueListPropsType } from "./components/KeyValueList/KeyValueList.schema";

export { Skeleton } from "./components/Skeleton/Skeleton";
export { SkeletonProps } from "./components/Skeleton/Skeleton.schema";
export type { SkeletonPropsType } from "./components/Skeleton/Skeleton.schema";

// Form input components
export { Input } from "./components/Input/Input";
export { InputProps } from "./components/Input/Input.schema";
export type { InputPropsType } from "./components/Input/Input.schema";

export { Select } from "./components/Select/Select";
export { SelectProps } from "./components/Select/Select.schema";
export type { SelectPropsType } from "./components/Select/Select.schema";

export { Textarea } from "./components/Textarea/Textarea";
export { TextareaProps } from "./components/Textarea/Textarea.schema";
export type { TextareaPropsType } from "./components/Textarea/Textarea.schema";

export { Checkbox } from "./components/Checkbox/Checkbox";
export { CheckboxProps } from "./components/Checkbox/Checkbox.schema";
export type { CheckboxPropsType } from "./components/Checkbox/Checkbox.schema";

export { Switch } from "./components/Switch/Switch";
export { SwitchProps } from "./components/Switch/Switch.schema";
export type { SwitchPropsType } from "./components/Switch/Switch.schema";

export { NumberInput } from "./components/NumberInput/NumberInput";
export { NumberInputProps } from "./components/NumberInput/NumberInput.schema";
export type { NumberInputPropsType } from "./components/NumberInput/NumberInput.schema";

export { MoneyInput, MoneyDisplay, formatMoney } from "./components/Money/Money";
export { MoneyInputProps, MoneyDisplayProps, DEFAULT_CURRENCIES } from "./components/Money/Money.schema";
export type { MoneyInputPropsType, MoneyDisplayPropsType } from "./components/Money/Money.schema";

export { RadioGroup } from "./components/RadioGroup/RadioGroup";
export { RadioGroupProps } from "./components/RadioGroup/RadioGroup.schema";
export type { RadioGroupPropsType } from "./components/RadioGroup/RadioGroup.schema";

export { Slider } from "./components/Slider/Slider";
export { SliderProps } from "./components/Slider/Slider.schema";
export type { SliderPropsType } from "./components/Slider/Slider.schema";

export { FileUpload } from "./components/FileUpload/FileUpload";
export { FileUploadProps } from "./components/FileUpload/FileUpload.schema";
export type { FileUploadPropsType } from "./components/FileUpload/FileUpload.schema";

export { Combobox } from "./components/Combobox/Combobox";
export { ComboboxProps } from "./components/Combobox/Combobox.schema";
export type { ComboboxPropsType } from "./components/Combobox/Combobox.schema";

export { DatePicker } from "./components/DatePicker/DatePicker";
export { DatePickerProps } from "./components/DatePicker/DatePicker.schema";
export type { DatePickerPropsType } from "./components/DatePicker/DatePicker.schema";

export { TimePicker } from "./components/TimePicker/TimePicker";
export { TimePickerProps } from "./components/TimePicker/TimePicker.schema";
export type { TimePickerPropsType } from "./components/TimePicker/TimePicker.schema";

export { ColorPicker } from "./components/ColorPicker/ColorPicker";
export { ColorPickerProps } from "./components/ColorPicker/ColorPicker.schema";
export type { ColorPickerPropsType } from "./components/ColorPicker/ColorPicker.schema";

export { InputOTP } from "./components/InputOTP/InputOTP";
export { InputOTPProps } from "./components/InputOTP/InputOTP.schema";
export type { InputOTPPropsType } from "./components/InputOTP/InputOTP.schema";

export { Rating } from "./components/Rating/Rating";
export { RatingProps } from "./components/Rating/Rating.schema";
export type { RatingPropsType } from "./components/Rating/Rating.schema";

export { MaskedInput } from "./components/MaskedInput/MaskedInput";
export { MaskedInputProps } from "./components/MaskedInput/MaskedInput.schema";
export type { MaskedInputPropsType } from "./components/MaskedInput/MaskedInput.schema";
export { KeyValueInput } from "./components/KeyValueInput/KeyValueInput";
export { KeyValueInputProps } from "./components/KeyValueInput/KeyValueInput.schema";
export type { KeyValueInputPropsType } from "./components/KeyValueInput/KeyValueInput.schema";
export { Gauge } from "./components/Gauge/Gauge";
export { GaugeProps } from "./components/Gauge/Gauge.schema";
export { Heatmap } from "./components/Heatmap/Heatmap";
export { HeatmapProps } from "./components/Heatmap/Heatmap.schema";
export { Schematic } from "./components/Schematic/Schematic";
export { SchematicProps } from "./components/Schematic/Schematic.schema";
export { Stepper } from "./components/Stepper/Stepper";
export { StepperProps } from "./components/Stepper/Stepper.schema";

// Wave 4 — data display
export { Tag } from "./components/Tag/Tag";
export { TagProps } from "./components/Tag/Tag.schema";
export type { TagPropsType } from "./components/Tag/Tag.schema";

export { Stat } from "./components/Stat/Stat";
export { SideNav } from "./components/SideNav/SideNav";
export type { SideNavPropsType } from "./components/SideNav/SideNav.schema";
export { StatProps } from "./components/Stat/Stat.schema";
export type { StatPropsType } from "./components/Stat/Stat.schema";

export { DescriptionList } from "./components/DescriptionList/DescriptionList";
export { DescriptionListProps } from "./components/DescriptionList/DescriptionList.schema";
export type { DescriptionListPropsType } from "./components/DescriptionList/DescriptionList.schema";

export { List } from "./components/List/List";
export { ListProps } from "./components/List/List.schema";
export type { ListPropsType } from "./components/List/List.schema";

export { SegmentedControl } from "./components/SegmentedControl/SegmentedControl";
export { SegmentedControlProps } from "./components/SegmentedControl/SegmentedControl.schema";
export type { SegmentedControlPropsType } from "./components/SegmentedControl/SegmentedControl.schema";

export { Tree } from "./components/Tree/Tree";
export { TreeProps } from "./components/Tree/Tree.schema";
export type { TreePropsType } from "./components/Tree/Tree.schema";

export { Transfer } from "./components/Transfer/Transfer";
export { TransferProps } from "./components/Transfer/Transfer.schema";
export type { TransferPropsType } from "./components/Transfer/Transfer.schema";

export { Cascader } from "./components/Cascader/Cascader";
export { CascaderProps } from "./components/Cascader/Cascader.schema";
export type { CascaderPropsType } from "./components/Cascader/Cascader.schema";

// Wave 5 — heavy composites
export { Calendar } from "./components/Calendar/Calendar";
export { CalendarProps } from "./components/Calendar/Calendar.schema";
export type { CalendarPropsType } from "./components/Calendar/Calendar.schema";

export { Kanban } from "./components/Kanban/Kanban";
export { KanbanProps } from "./components/Kanban/Kanban.schema";
export type { KanbanPropsType } from "./components/Kanban/Kanban.schema";

export { ResourceTimeline } from "./components/ResourceTimeline/ResourceTimeline";
export { ResourceTimelineProps } from "./components/ResourceTimeline/ResourceTimeline.schema";
export type { ResourceTimelinePropsType } from "./components/ResourceTimeline/ResourceTimeline.schema";

export { RichTextEditor } from "./components/RichTextEditor/RichTextEditor";
export { RichTextEditorProps } from "./components/RichTextEditor/RichTextEditor.schema";
export type { RichTextEditorPropsType } from "./components/RichTextEditor/RichTextEditor.schema";

export { Carousel } from "./components/Carousel/Carousel";
export { CarouselProps } from "./components/Carousel/Carousel.schema";
export type { CarouselPropsType } from "./components/Carousel/Carousel.schema";

export { Lightbox } from "./components/Lightbox/Lightbox";
export { LightboxProps } from "./components/Lightbox/Lightbox.schema";
export type { LightboxPropsType } from "./components/Lightbox/Lightbox.schema";

export { CodeBlock } from "./components/CodeBlock/CodeBlock";
export { CodeBlockProps } from "./components/CodeBlock/CodeBlock.schema";
export type { CodeBlockPropsType } from "./components/CodeBlock/CodeBlock.schema";

export { QRCode } from "./components/QRCode/QRCode";
export { QRCodeProps } from "./components/QRCode/QRCode.schema";
export type { QRCodePropsType } from "./components/QRCode/QRCode.schema";

// Wave 6 — device & capture
export { BarcodeScanner } from "./components/BarcodeScanner/BarcodeScanner";
export { BarcodeScannerProps } from "./components/BarcodeScanner/BarcodeScanner.schema";
export type { BarcodeScannerPropsType } from "./components/BarcodeScanner/BarcodeScanner.schema";
export { CameraCapture } from "./components/CameraCapture/CameraCapture";
export { CameraCaptureProps } from "./components/CameraCapture/CameraCapture.schema";
export type { CameraCapturePropsType } from "./components/CameraCapture/CameraCapture.schema";

export { Scanner } from "./components/Scanner/Scanner";
export { ScannerProps } from "./components/Scanner/Scanner.schema";
export type { ScannerPropsType } from "./components/Scanner/Scanner.schema";

export { ValidationChecklist } from "./components/ValidationChecklist/ValidationChecklist";
export { ValidationChecklistProps } from "./components/ValidationChecklist/ValidationChecklist.schema";
export type { ValidationChecklistPropsType } from "./components/ValidationChecklist/ValidationChecklist.schema";

// Motion components
export { FadeIn } from "./components/FadeIn/FadeIn";
export { FadeInProps } from "./components/FadeIn/FadeIn.schema";
export type { FadeInPropsType } from "./components/FadeIn/FadeIn.schema";

export { Stagger } from "./components/Stagger/Stagger";
export { StaggerProps } from "./components/Stagger/Stagger.schema";
export type { StaggerPropsType } from "./components/Stagger/Stagger.schema";

// Passthrough wrapper — handles LLM-generated <Tabs><TabPanel>...</TabPanel></Tabs>
// shapes that don't match the v2 TabsNode contract (tabs[] + children).
export { TabPanel } from "./components/TabPanel/TabPanel";
export { TabPanelProps } from "./components/TabPanel/TabPanel";
export type { TabPanelPropsType } from "./components/TabPanel/TabPanel";

// Escape-hatch component
export { CustomBlock } from "./components/CustomBlock/CustomBlock";
export { CustomBlockProps } from "./components/CustomBlock/CustomBlock.schema";
export type { CustomBlockPropsType } from "./components/CustomBlock/CustomBlock.schema";

// Register-aware variant selector
export * from "./components/variants";

// Tier 2 — data visualisation + display
export { Sparkline, type SparklineProps } from "./components/Sparkline/Sparkline";
export { SparklineProps as SparklinePropsSchema } from "./components/Sparkline/Sparkline.schema";

export { Chart, type ChartProps } from "./components/Chart/Chart";
export { ChartProps as ChartPropsSchema } from "./components/Chart/Chart.schema";

export { DataGrid, type DataGridProps } from "./components/DataGrid/DataGrid";
export { DataGridProps as DataGridPropsSchema } from "./components/DataGrid/DataGrid.schema";
export type { DataGridPropsType } from "./components/DataGrid/DataGrid.schema";

export { EditableLineGrid, type EditableLineGridProps } from "./components/EditableLineGrid/EditableLineGrid";
export { EditableLineGridProps as EditableLineGridPropsSchema } from "./components/EditableLineGrid/EditableLineGrid.schema";
export type { EditableLineGridPropsType } from "./components/EditableLineGrid/EditableLineGrid.schema";

export { Timeline } from "./components/Timeline/Timeline";
export { TimelineProps as TimelinePropsSchema } from "./components/Timeline/Timeline.schema";
export type { TimelinePropsType } from "./components/Timeline/Timeline.schema";

// Tier 2 — enterprise components
export { ApprovalStepper } from "./components/ApprovalStepper/ApprovalStepper";
export { ApprovalStepperProps as ApprovalStepperPropsSchema } from "./components/ApprovalStepper/ApprovalStepper.schema";
export type { ApprovalStepperPropsType } from "./components/ApprovalStepper/ApprovalStepper.schema";

export { PersonCard } from "./components/PersonCard/PersonCard";
export { PersonCardProps as PersonCardPropsSchema } from "./components/PersonCard/PersonCard.schema";
export type { PersonCardPropsType } from "./components/PersonCard/PersonCard.schema";

export { ActivityFeed } from "./components/ActivityFeed/ActivityFeed";
export { ActivityFeedProps as ActivityFeedPropsSchema } from "./components/ActivityFeed/ActivityFeed.schema";
export type { ActivityFeedPropsType } from "./components/ActivityFeed/ActivityFeed.schema";

export { FilterBar } from "./components/FilterBar/FilterBar";
export { FilterBarProps as FilterBarPropsSchema } from "./components/FilterBar/FilterBar.schema";
export type { FilterBarPropsType } from "./components/FilterBar/FilterBar.schema";
export { useUrlState } from "./style/useUrlState";

export { CommandPalette } from "./components/CommandPalette/CommandPalette";
export { CommandPaletteProps as CommandPalettePropsSchema } from "./components/CommandPalette/CommandPalette.schema";
export type { CommandPalettePropsType } from "./components/CommandPalette/CommandPalette.schema";

export { EmptyStateRich } from "./components/EmptyStateRich/EmptyStateRich";
export { EmptyStateRichProps as EmptyStateRichPropsSchema } from "./components/EmptyStateRich/EmptyStateRich.schema";
export type { EmptyStateRichPropsType } from "./components/EmptyStateRich/EmptyStateRich.schema";

export { DateRangePicker } from "./components/DateRangePicker/DateRangePicker";
export { DateRangePickerProps as DateRangePickerPropsSchema } from "./components/DateRangePicker/DateRangePicker.schema";
export type { DateRangePickerPropsType } from "./components/DateRangePicker/DateRangePicker.schema";

export { MultiSelect } from "./components/MultiSelect/MultiSelect";
export { MultiSelectProps as MultiSelectPropsSchema } from "./components/MultiSelect/MultiSelect.schema";
export type { MultiSelectPropsType } from "./components/MultiSelect/MultiSelect.schema";

// Tier 2 Wave 4 — Layout primitives
export { AppShell } from "./components/AppShell/AppShell";
export { AppShellProps as AppShellPropsSchema, type AppShellPropsType } from "./components/AppShell/AppShell.schema";

export { InspectorPanel } from "./components/InspectorPanel/InspectorPanel";
export { InspectorPanelProps as InspectorPanelPropsSchema, type InspectorPanelPropsType } from "./components/InspectorPanel/InspectorPanel.schema";

export { TabPanelWithDeepLink } from "./components/TabPanelWithDeepLink/TabPanelWithDeepLink";
export { TabPanelWithDeepLinkProps as TabPanelWithDeepLinkPropsSchema, type TabPanelWithDeepLinkPropsType } from "./components/TabPanelWithDeepLink/TabPanelWithDeepLink.schema";

export { Drawer } from "./components/Drawer/Drawer";
export { DrawerProps } from "./components/Drawer/Drawer.schema";
export type { DrawerPropsType } from "./components/Drawer/Drawer.schema";

export { ContextMenu } from "./components/ContextMenu/ContextMenu";
export { ContextMenuProps } from "./components/ContextMenu/ContextMenu.schema";
export type { ContextMenuPropsType } from "./components/ContextMenu/ContextMenu.schema";

export { HoverCard } from "./components/HoverCard/HoverCard";
export { HoverCardProps } from "./components/HoverCard/HoverCard.schema";
export type { HoverCardPropsType } from "./components/HoverCard/HoverCard.schema";

export { Menubar } from "./components/Menubar/Menubar";
export { MenubarProps } from "./components/Menubar/Menubar.schema";
export type { MenubarPropsType } from "./components/Menubar/Menubar.schema";

// Wave 3 — feedback
export { Progress } from "./components/Progress/Progress";
export { ProgressProps } from "./components/Progress/Progress.schema";
export type { ProgressPropsType } from "./components/Progress/Progress.schema";

export { Spinner } from "./components/Spinner/Spinner";
export { SpinnerProps } from "./components/Spinner/Spinner.schema";
export type { SpinnerPropsType } from "./components/Spinner/Spinner.schema";
export { Redirect } from "./components/Redirect/Redirect";
export { RedirectProps } from "./components/Redirect/Redirect.schema";
export type { RedirectPropsType } from "./components/Redirect/Redirect.schema";

export { Banner } from "./components/Banner/Banner";
export { BannerProps } from "./components/Banner/Banner.schema";
export type { BannerPropsType } from "./components/Banner/Banner.schema";

// Side-effect import of the motion stylesheet. Consumers should import
// once at the app root: `import "@tentoroforge/library/style/motion.css";`
// (NOTE: not auto-imported here to keep the package's main JS entry pure.)

// Spec C Slice 7 — interaction depth
export { BulkActionBar } from "./components/BulkActionBar/BulkActionBar";
export { BulkActionBarProps } from "./components/BulkActionBar/BulkActionBar.schema";
export type { BulkActionBarPropsType } from "./components/BulkActionBar/BulkActionBar.schema";
export { SavedViewsPicker } from "./components/SavedViewsPicker/SavedViewsPicker";
export { SavedViewsPickerProps } from "./components/SavedViewsPicker/SavedViewsPicker.schema";
export type { SavedViewsPickerPropsType } from "./components/SavedViewsPicker/SavedViewsPicker.schema";
export { GlobalSearch } from "./components/GlobalSearch/GlobalSearch";
export { GlobalSearchProps } from "./components/GlobalSearch/GlobalSearch.schema";
export type { GlobalSearchPropsType } from "./components/GlobalSearch/GlobalSearch.schema";

// SEARCH-3 — full-text search input + results panel, backed by a shared store.
export { SearchInput } from "./components/SearchInput/SearchInput";
export { SearchInputProps } from "./components/SearchInput/SearchInput.schema";
export type { SearchInputPropsType } from "./components/SearchInput/SearchInput.schema";
export {
  getSearchState,
  setSearchState,
  resetSearchState,
  subscribeSearch,
} from "./components/SearchInput/searchStore";
export type { SearchHit, SearchState } from "./components/SearchInput/searchStore";
export { SearchResults } from "./components/SearchResults/SearchResults";
export { SearchResultsProps } from "./components/SearchResults/SearchResults.schema";
export type { SearchResultsPropsType } from "./components/SearchResults/SearchResults.schema";
export { KeyboardShortcuts } from "./components/KeyboardShortcuts/KeyboardShortcuts";
export { KeyboardShortcutsProps } from "./components/KeyboardShortcuts/KeyboardShortcuts.schema";
export type { KeyboardShortcutsPropsType } from "./components/KeyboardShortcuts/KeyboardShortcuts.schema";
// Spec C Slice 8 — dark-mode toggle
export { ThemeToggle } from "./components/ThemeToggle/ThemeToggle";
export { ThemeToggleProps } from "./components/ThemeToggle/ThemeToggle.schema";
export type { ThemeTogglePropsType } from "./components/ThemeToggle/ThemeToggle.schema";
// Spec C Slice 9 — illustrated empty state
export { IllustratedEmpty } from "./components/IllustratedEmpty/IllustratedEmpty";
export { IllustratedEmptyProps } from "./components/IllustratedEmpty/IllustratedEmpty.schema";
export type { IllustratedEmptyPropsType } from "./components/IllustratedEmpty/IllustratedEmpty.schema";

// Spec E Wave 1 — advanced interactions
export { UndoManager } from "./components/UndoManager/UndoManager";
export { UndoManagerProps } from "./components/UndoManager/UndoManager.schema";
export type { UndoManagerPropsType } from "./components/UndoManager/UndoManager.schema";
export type { UndoEntry } from "./components/UndoManager/UndoManager";
export { PresenceIndicator } from "./components/PresenceIndicator/PresenceIndicator";
export { PresenceIndicatorProps } from "./components/PresenceIndicator/PresenceIndicator.schema";
export type { PresenceIndicatorPropsType } from "./components/PresenceIndicator/PresenceIndicator.schema";
export type { PresenceUser } from "./components/PresenceIndicator/PresenceIndicator";
export {
  OptimisticProvider,
  useOptimisticState,
} from "./components/OptimisticProvider/OptimisticProvider";
export { OptimisticProviderProps } from "./components/OptimisticProvider/OptimisticProvider.schema";
export type { OptimisticProviderPropsType } from "./components/OptimisticProvider/OptimisticProvider.schema";

// Spec E Wave 3 — advanced UX patterns
export { Wizard } from "./components/Wizard/Wizard";
export { WizardProps } from "./components/Wizard/Wizard.schema";
export type {
  WizardPropsType,
  WizardStepType,
  WizardFieldType,
} from "./components/Wizard/Wizard.schema";
export { SplitView } from "./components/SplitView/SplitView";
export { SplitViewProps } from "./components/SplitView/SplitView.schema";
export type { SplitViewPropsType } from "./components/SplitView/SplitView.schema";
export {
  FilterBuilder,
  encode as encodeFilterExpression,
  decode as decodeFilterExpression,
} from "./components/FilterBuilder/FilterBuilder";
export { FilterBuilderProps } from "./components/FilterBuilder/FilterBuilder.schema";
export type {
  FilterBuilderPropsType,
  FilterFieldType,
} from "./components/FilterBuilder/FilterBuilder.schema";
export { TourOverlay } from "./components/TourOverlay/TourOverlay";
export { TourOverlayProps } from "./components/TourOverlay/TourOverlay.schema";
export type {
  TourOverlayPropsType,
  TourStepType,
} from "./components/TourOverlay/TourOverlay.schema";
