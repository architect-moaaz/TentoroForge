// The application's coded root page — `/` written as React (`pageCode`).
//
// `/` cannot be a page file of its own here: the optional catch-all
// `[[...slug]]` already answers it, and Next refuses two answers for one URL.
// So the catch-all renders this module for `/` when it holds a page. `_root`
// is a private folder (leading underscore): Next never routes it itself.
//
// This is the scaffold's stub: no coded root, so `/` is served as it always
// was. The frontend projection replaces it when the Blueprint has one.
export const hasCodeRoot = false;

export default async function RootPage(_props: {
  params: Promise<Record<string, string>>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  return null;
}
