/**
 * Route-aware prop editing.
 *
 * Four audit entries asked for the same thing: "I wanted a picker listing the
 * project's real routes (the editor already lists them in the Pages rail)"
 * (Redirect), "no route picker — the editor knows this project's routes and
 * does not offer them" (Link), "a route picker for `target` instead of free
 * text" (NavLink), "no validation that the route exists in this project"
 * (CommandPalette). A fifth asked for a row-per-crumb editor with a label field
 * and a route picker instead of a raw JSON textarea (Breadcrumb).
 *
 * The activation rule under test is the important part: it keys on the VALUE's
 * shape — a root-relative string is a route — not on the prop's name or the
 * component's. A name list (navigate / to / target / href) would pass these
 * tests today and miss the sixth destination prop anyone adds.
 */
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { useEditorStore } from "@/lib/editor-store";
import { TextControl, RowsControl } from "@/components/properties/PropControls";
import {
  looksLikeRoute,
  routeExists,
} from "@/components/properties/PropControls/RouteControl";

/** The project's Pages rail, as the store holds it. */
function seedRoutes(routes: string[]) {
  useEditorStore.setState({
    artifacts: {
      pageSchemas: {},
      navFlow: {
        pages: routes.map((route, i) => ({ id: `p${i}`, route, title: route })),
      },
      tokens: {},
    } as any,
  });
}

beforeEach(() => seedRoutes(["/", "/items", "/items/new", "/items/[id]"]));
afterEach(cleanup);

describe("what counts as a route", () => {
  it("is a root-relative path, and nothing else", () => {
    expect(looksLikeRoute("/items")).toBe(true);
    expect(looksLikeRoute("https://example.com/items")).toBe(false);
    expect(looksLikeRoute("#main")).toBe(false);
    expect(looksLikeRoute("Learn more")).toBe(false);
    expect(looksLikeRoute(undefined)).toBe(false);
    // "/" alone is excluded: it is also an ordinary text value (a Breadcrumb
    // separator), and flagging it would be noise on a prop that is not a route.
    expect(looksLikeRoute("/")).toBe(false);
  });

  it("resolves a dynamic segment the way the renderer does", () => {
    const routes = ["/items", "/items/[id]"];
    expect(routeExists(routes, "/items/42")).toBe(true);
    expect(routeExists(routes, "/items")).toBe(true);
    expect(routeExists(routes, "/items/42/edit")).toBe(false);
    expect(routeExists(routes, "/nope")).toBe(false);
    // Query and hash are not part of the path.
    expect(routeExists(routes, "/items?tab=all")).toBe(true);
  });
});

describe("a text prop holding a route", () => {
  it("offers the project's real routes as suggestions", () => {
    render(<TextControl label="navigate" value="/items" onChange={() => {}} />);
    const list = document.querySelector("[data-route-suggestions]");
    expect(list).not.toBeNull();
    const offered = Array.from(list!.querySelectorAll("option")).map(
      (o) => (o as HTMLOptionElement).value,
    );
    expect(offered).toContain("/items");
    expect(offered).toContain("/items/new");
    // The input is wired to the list, not merely accompanied by it.
    const input = screen.getByLabelText("navigate") as HTMLInputElement;
    expect(input.getAttribute("list")).toBe(list!.getAttribute("id"));
  });

  it("says so when the route reaches no page in this project", () => {
    render(<TextControl label="to" value="/itmes" onChange={() => {}} />);
    expect(screen.getByText(/No page in this project has the route/)).toBeTruthy();
  });

  it("stays quiet for a route that does exist, including a dynamic one", () => {
    render(<TextControl label="to" value="/items/7" onChange={() => {}} />);
    expect(document.querySelector("[data-route-warning]")).toBeNull();
  });

  it("leaves ordinary text alone — no list, no warning", () => {
    render(<TextControl label="label" value="Learn more" onChange={() => {}} />);
    expect(document.querySelector("[data-route-suggestions]")).toBeNull();
    expect(document.querySelector("[data-route-warning]")).toBeNull();
  });

  it("never rewrites what the user typed", () => {
    const seen: string[] = [];
    render(
      <TextControl label="to" value="/nope" onChange={(v: any) => seen.push(v)} />,
    );
    // An unknown route is advisory: an external URL, a page not created yet and
    // a templated path are all legitimate, so nothing is corrected for the user.
    expect(seen).toEqual([]);
    fireEvent.change(screen.getByLabelText("to"), { target: { value: "/it" } });
    expect(seen).toEqual(["/it"]);
  });

  it("degrades to a plain box when the project has no routes yet", () => {
    seedRoutes([]);
    render(<TextControl label="to" value="/items" onChange={() => {}} />);
    expect(document.querySelector("[data-route-suggestions]")).toBeNull();
    expect(document.querySelector("[data-route-warning]")).toBeNull();
  });
});

describe("rows that carry a destination", () => {
  it("edits a {label, href} row as fields instead of raw JSON", () => {
    // The Breadcrumb complaint verbatim: "the ITEMS editor is a raw JSON
    // textarea with the note 'Editing as JSON — no value / key / id on every
    // row'". A crumb has no identity key and never will; having a label is
    // enough to put fields on it.
    const rows = [{ label: "Items", href: "/items" }, { label: "Edit" }];
    render(<RowsControl label="items" value={rows} onChange={() => {}} />);
    expect(screen.queryByLabelText("items JSON")).toBeNull();
    // Label leads, because that is the part the user reads.
    expect((screen.getByLabelText("items row 1 value") as HTMLInputElement).value)
      .toBe("Items");
  });

  it("gives a destination cell the same suggestions and warning", () => {
    const rows = [{ label: "Items", href: "/items" }, { label: "Edit", href: "/nope" }];
    render(<RowsControl label="items" value={rows} onChange={() => {}} />);
    const href1 = screen.getByLabelText("items row 1 href") as HTMLInputElement;
    expect(href1.value).toBe("/items");
    expect(href1.getAttribute("list")).toBeTruthy();
    expect(screen.getByText(/No page in this project has the route/)).toBeTruthy();
  });

  it("still refuses a shape with nothing nameable in it", () => {
    render(<RowsControl label="items" value={[{ href: "/a", note: "n" }]} onChange={() => {}} />);
    expect(screen.getByLabelText("items JSON")).toBeTruthy();
  });
});
