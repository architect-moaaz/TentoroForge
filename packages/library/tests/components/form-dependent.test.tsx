import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Form } from "../../src/components/Form/Form";
import type { FormDataFetcher } from "../../src/util/fallbackFetchData";

// S1c — dependent dropdowns + onChange populate. A Select whose
// `interaction.optionsFrom.filter` references another field re-fetches its
// options when that field changes; a field with `interaction.onChange` fetches a
// record on change and sets other fields. The fetch layer is injected so no
// network is hit — the real default is the `/api/data` loader.

describe("Form — dependent dropdowns (optionsFrom re-fetch)", () => {
  it("re-fetches product options with the category filter and repopulates them", async () => {
    const fetchData: FormDataFetcher = vi.fn(async (resource, filter) => {
      if (resource === "products") {
        const cat = filter?.categoryId;
        if (cat === "c1") {
          return [
            { id: "p1", name: "Apple" },
            { id: "p2", name: "Banana" },
          ];
        }
        if (cat === "c2") {
          return [{ id: "p3", name: "Carrot" }];
        }
      }
      return [];
    });

    render(
      <Form
        workflow="createOrder"
        defaultValues={{ categoryId: "", productId: "" }}
        fields={[
          {
            kind: "select",
            name: "categoryId",
            label: "Category",
            options: [
              { value: "c1", label: "Fruit" },
              { value: "c2", label: "Veg" },
            ],
          },
          {
            kind: "select",
            name: "productId",
            label: "Product",
            options: [],
            interaction: {
              optionsFrom: {
                source: "products",
                value: "id",
                label: "name",
                filter: { categoryId: "{{categoryId}}" },
              },
              dependsOn: ["categoryId"],
            },
          },
        ]}
        __dispatch={vi.fn()}
        __fetchData={fetchData}
      />,
    );

    const productSelect = screen.getByLabelText("Product") as HTMLSelectElement;
    // No category chosen yet → no fetch, product has only the placeholder.
    expect(fetchData).not.toHaveBeenCalled();
    expect(productSelect.querySelectorAll("option")).toHaveLength(1); // just "—"

    // Choose Fruit → fetch products?categoryId=c1, options become Apple/Banana.
    fireEvent.change(screen.getByLabelText("Category"), { target: { value: "c1" } });

    await waitFor(() => {
      expect(fetchData).toHaveBeenCalledWith("products", { categoryId: "c1" });
      expect(screen.getByRole("option", { name: "Apple" })).toBeInTheDocument();
      expect(screen.getByRole("option", { name: "Banana" })).toBeInTheDocument();
    });

    // Switch to Veg → re-fetch with c2, options replaced by Carrot.
    fireEvent.change(screen.getByLabelText("Category"), { target: { value: "c2" } });
    await waitFor(() => {
      expect(fetchData).toHaveBeenCalledWith("products", { categoryId: "c2" });
      expect(screen.getByRole("option", { name: "Carrot" })).toBeInTheDocument();
    });
    expect(screen.queryByRole("option", { name: "Apple" })).not.toBeInTheDocument();
  });

  it("ignores a stale (slower first) response when a second change lands first", async () => {
    // c1 resolves slowly, c2 resolves immediately — the fast second response must
    // win even though the first resolves afterwards.
    let resolveSlow: ((rows: unknown[]) => void) | undefined;
    const fetchData: FormDataFetcher = vi.fn(async (_resource, filter) => {
      if (filter?.categoryId === "c1") {
        return new Promise<unknown[]>((res) => {
          resolveSlow = res;
        });
      }
      return [{ id: "p3", name: "Carrot" }];
    });

    render(
      <Form
        workflow="createOrder"
        defaultValues={{ categoryId: "", productId: "" }}
        fields={[
          {
            kind: "select",
            name: "categoryId",
            label: "Category",
            options: [
              { value: "c1", label: "Fruit" },
              { value: "c2", label: "Veg" },
            ],
          },
          {
            kind: "select",
            name: "productId",
            label: "Product",
            options: [],
            interaction: {
              optionsFrom: { source: "products", value: "id", label: "name", filter: { categoryId: "{{categoryId}}" } },
              dependsOn: ["categoryId"],
            },
          },
        ]}
        __dispatch={vi.fn()}
        __fetchData={fetchData}
      />,
    );

    // First change (slow, pending), then a fast second change that resolves.
    fireEvent.change(screen.getByLabelText("Category"), { target: { value: "c1" } });
    fireEvent.change(screen.getByLabelText("Category"), { target: { value: "c2" } });

    await waitFor(() => {
      expect(screen.getByRole("option", { name: "Carrot" })).toBeInTheDocument();
    });

    // Now let the stale first response resolve — it must be ignored.
    resolveSlow?.([
      { id: "p1", name: "Apple" },
      { id: "p2", name: "Banana" },
    ]);

    // Give the ignored promise a tick; options stay as the fast (c2) result.
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.getByRole("option", { name: "Carrot" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Apple" })).not.toBeInTheDocument();
  });
});

describe("Form — onChange populate", () => {
  it("fetches the selected customer and sets the address field", async () => {
    const fetchData: FormDataFetcher = vi.fn(async (resource, filter) => {
      if (resource === "customers" && filter?.id === "cust-1") {
        return [{ id: "cust-1", name: "Acme", address: "123 Main St" }];
      }
      return [];
    });

    render(
      <Form
        workflow="createInvoice"
        defaultValues={{ customerId: "", address: "" }}
        fields={[
          {
            kind: "select",
            name: "customerId",
            label: "Customer",
            options: [
              { value: "cust-1", label: "Acme" },
              { value: "cust-2", label: "Globex" },
            ],
            interaction: {
              onChange: {
                fetch: { resource: "customers", by: "id", from: "customerId" },
                set: { address: "{{result.address}}" },
              },
            },
          },
          { kind: "text", name: "address", label: "Address" },
        ]}
        __dispatch={vi.fn()}
        __fetchData={fetchData}
      />,
    );

    const address = screen.getByLabelText("Address") as HTMLInputElement;
    expect(address.value).toBe("");

    fireEvent.change(screen.getByLabelText("Customer"), { target: { value: "cust-1" } });

    await waitFor(() => {
      expect(fetchData).toHaveBeenCalledWith("customers", { id: "cust-1" });
      expect(address.value).toBe("123 Main St");
    });
  });
});

describe("Form — regression: plain select unaffected", () => {
  it("renders a static select's options and never fetches", async () => {
    const fetchData = vi.fn();
    const dispatch = vi.fn();
    render(
      <Form
        workflow="createThing"
        defaultValues={{ color: "" }}
        fields={[
          {
            kind: "select",
            name: "color",
            label: "Color",
            options: [
              { value: "r", label: "Red" },
              { value: "g", label: "Green" },
            ],
          },
        ]}
        __dispatch={dispatch}
        __fetchData={fetchData as unknown as FormDataFetcher}
      />,
    );

    expect(screen.getByRole("option", { name: "Red" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Green" })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Color"), { target: { value: "g" } });
    // A plain select triggers no data fetch.
    await new Promise((r) => setTimeout(r, 0));
    expect(fetchData).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: /save|submit/i }));
    expect(dispatch).toHaveBeenCalledWith("createThing", { color: "g" });
  });
});
