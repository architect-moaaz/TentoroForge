// The app SDK (native) — the one import surface for screens: `import { useList,
// useWorkflow, workflows, pages, href } from "@/sdk"`. Same names as the web
// SDK's `@/sdk` and `@/sdk/client`, so a screen reads like a web page.
//
// The generated modules (schema, workflows, pages, widgets) are re-exported
// whole: their handles and types are what makes a screen compile against THIS
// app. Everything else here is the fixed half, identical in every app.

// Generated: typed handles and the schema (same as the web's).
export * from "./schema";
export * from "./workflows";
export * from "./pages";
export * from "./widgets";

// Reading data (the web's `@/sdk/server`, over HTTP).
export {
  useList, useRecord, useRecords, useCount, useTotal, useSeries, useQuery, useWidget, useSimilar, useNear, useMe, useLive,
  type ReadState, type ListState,
} from "./data";
export type {
  CountWhere, DateRange, Dimension, ListOptions, Measure, Me, NearOptions, Page, QueryOptions, QueryRow, SeriesOptions, SeriesPoint,
  Similar, SimilarOptions, Where, WidgetData, WidgetOptions,
} from "./reads";

// Changing data: every change is a workflow.
export { useWorkflow, type RunResult } from "./workflow";

// Who is signed in.
export { SessionProvider, useSession, useOrganisations, useSignInMethods, type SessionStatus } from "./auth";
export type { Organisation, SessionUser, SignInMethods, SignInOutcome } from "./signin";

// Moving about, saying things, files, places, money, language.
export { useNav, useParams, type Nav } from "./nav";
export { toast, useToast, ToastProvider } from "./toast";
export { fileSource, pickImage, pickDocument, uploadFile, type PickedFile, type UploadResult } from "./files";
export { formatCell, formatDate, formatNumber, formatPercent, humanize } from "./format";
export { distanceKm, formatDistance, parseNear, roundPoint, isPoint, type GeoPoint } from "./geo";
export { askPosition } from "./location";
export { CURRENCY, formatMoney } from "./money";
export { useT, useLanguage } from "./i18n";
export { apiFetch, apiJson, appUrl, appConfigured } from "./api";
