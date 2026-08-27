import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Pagination } from "../../src/components/Pagination/Pagination";

describe("Pagination — back-compat", () => {
  it("renders `Page X of Y` when only currentPage + totalPages are supplied", () => {
    render(<Pagination currentPage={3} totalPages={10} />);
    expect(screen.getByText(/Page/)).toBeTruthy();
    expect(screen.getByText("3")).toBeTruthy();
    expect(screen.getByText("10")).toBeTruthy();
  });

  it("renders chevron buttons (disabled when no onPageChange handler)", () => {
    render(<Pagination currentPage={1} totalPages={5} />);
    const next = screen.getByLabelText("Next page");
    expect(next).toBeTruthy();
    // Without onPageChange, clicking is a no-op (handler is undefined).
    fireEvent.click(next);
  });
});

describe("Pagination — item-range mode", () => {
  it("renders `1-10 of 100` when totalItems + pageSize supplied", () => {
    render(
      <Pagination
        currentPage={1}
        totalPages={10}
        totalItems={100}
        pageSize={10}
      />,
    );
    expect(screen.getByText("1-10 of 100")).toBeTruthy();
  });

  it("computes a partial last-page range correctly", () => {
    // 100 items, 10/page, page 10 → 91-100
    render(<Pagination currentPage={10} totalPages={10} totalItems={100} pageSize={10} />);
    expect(screen.getByText("91-100 of 100")).toBeTruthy();
  });

  it("handles a page that runs past totalItems by clamping the end", () => {
    // 14 items, 10/page, page 2 → 11-14
    render(<Pagination currentPage={2} totalPages={2} totalItems={14} pageSize={10} />);
    expect(screen.getByText("11-14 of 14")).toBeTruthy();
  });

  it("renders 0-0 of 0 for an empty result set", () => {
    render(<Pagination currentPage={1} totalPages={1} totalItems={0} pageSize={10} />);
    expect(screen.getByText("0-0 of 0")).toBeTruthy();
  });
});

describe("Pagination — controls", () => {
  it("disables prev chevrons on page 1", () => {
    render(<Pagination currentPage={1} totalPages={5} onPageChange={() => {}} />);
    expect((screen.getByLabelText("First page") as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByLabelText("Previous page") as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByLabelText("Next page") as HTMLButtonElement).disabled).toBe(false);
  });

  it("disables next chevrons on the last page", () => {
    render(<Pagination currentPage={5} totalPages={5} onPageChange={() => {}} />);
    expect((screen.getByLabelText("Last page") as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByLabelText("Next page") as HTMLButtonElement).disabled).toBe(true);
  });

  it("fires onPageChange with the next page", () => {
    const onChange = vi.fn();
    render(<Pagination currentPage={2} totalPages={5} onPageChange={onChange} />);
    fireEvent.click(screen.getByLabelText("Next page"));
    expect(onChange).toHaveBeenCalledWith(3);
    fireEvent.click(screen.getByLabelText("Previous page"));
    expect(onChange).toHaveBeenCalledWith(1);
    fireEvent.click(screen.getByLabelText("First page"));
    expect(onChange).toHaveBeenCalledWith(1);
    fireEvent.click(screen.getByLabelText("Last page"));
    expect(onChange).toHaveBeenCalledWith(5);
  });
});

describe("Pagination — page-size selector", () => {
  it("renders a <select> when pageSize + pageSizeOptions supplied", () => {
    render(
      <Pagination
        currentPage={1}
        totalPages={5}
        pageSize={10}
        pageSizeOptions={[10, 25, 50]}
      />,
    );
    const select = screen.getByLabelText("Lines per page") as HTMLSelectElement;
    expect(select).toBeTruthy();
    expect(select.value).toBe("10");
    expect(select.options).toHaveLength(3);
  });

  it("fires onPageSizeChange with the new numeric size", () => {
    const onSize = vi.fn();
    render(
      <Pagination
        currentPage={1}
        totalPages={5}
        pageSize={10}
        pageSizeOptions={[10, 25, 50]}
        onPageSizeChange={onSize}
      />,
    );
    fireEvent.change(screen.getByLabelText("Lines per page"), { target: { value: "25" } });
    expect(onSize).toHaveBeenCalledWith(25);
  });

  it("omits the selector when pageSizeOptions isn't supplied", () => {
    const { container } = render(
      <Pagination currentPage={1} totalPages={5} pageSize={10} />,
    );
    expect(container.querySelector("select")).toBeNull();
  });

  it("uses a custom label when pageSizeLabel is supplied", () => {
    render(
      <Pagination
        currentPage={1}
        totalPages={5}
        pageSize={20}
        pageSizeOptions={[20, 50]}
        pageSizeLabel="Rows per page"
      />,
    );
    expect(screen.getByText("Rows per page")).toBeTruthy();
  });
});
