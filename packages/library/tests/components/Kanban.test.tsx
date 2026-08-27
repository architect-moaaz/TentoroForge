import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { Kanban } from "../../src/components/Kanban/Kanban";
import { KanbanProps } from "../../src/components/Kanban/Kanban.schema";

const cols = [
  { id: "todo", title: "To Do", cards: [{ id: "c1", title: "Gate check" }] },
  { id: "doing", title: "In Progress", cards: [] },
];

describe("Kanban", () => {
  it("renders columns with their titles and cards", () => {
    render(<Kanban columns={cols} />);
    expect(screen.getByText("To Do")).toBeInTheDocument();
    expect(screen.getByText("In Progress")).toBeInTheDocument();
    expect(screen.getByText("Gate check")).toBeInTheDocument();
  });
  it("moves a card to the next column and fires onCardMove", () => {
    const onCardMove = vi.fn();
    render(<Kanban columns={cols} onCardMove={onCardMove} />);
    fireEvent.click(screen.getByRole("button", { name: /move Gate check right/i }));
    expect(onCardMove).toHaveBeenCalledWith("c1", "todo", "doing");
    const doing = screen.getByTestId("kanban-col-doing");
    expect(within(doing).getByText("Gate check")).toBeInTheDocument();
  });
  it("validates props", () => {
    expect(() => KanbanProps.parse({ columns: cols })).not.toThrow();
    expect(() => KanbanProps.parse({})).not.toThrow();
  });
});

const tasks = [
  { id: "1", title: "Design schema", status: "todo", priority: "high", assignee: "Ada Lovelace" },
  { id: "2", title: "Build API", status: "in_progress", priority: "medium", assignee: "Alan Turing" },
  { id: "3", title: "Write tests", status: "in_progress", priority: "low" },
  { id: "4", title: "Ship it", status: "done" },
];

describe("Kanban — data-driven mode", () => {
  it("derives columns from distinct groupBy values and humanizes them", () => {
    render(<Kanban data={tasks} groupBy="status" />);
    expect(screen.getByText("Todo")).toBeInTheDocument();
    expect(screen.getByText("In Progress")).toBeInTheDocument();
    expect(screen.getByText("Done")).toBeInTheDocument();
  });

  it("honours an explicit columnOrder (status enum) including empty columns", () => {
    render(<Kanban data={tasks} groupBy="status" columnOrder={["todo", "in_progress", "review", "done"]} />);
    expect(screen.getByTestId("kanban-col-review")).toBeInTheDocument();
    expect(screen.getAllByTestId(/^kanban-col-/).length).toBe(4);
  });

  it("places each record as a card in its group using cardTitle", () => {
    render(<Kanban data={tasks} groupBy="status" cardTitle="title" />);
    const inProgress = screen.getByTestId("kanban-col-in_progress");
    expect(within(inProgress).getAllByTestId(/^kanban-card-/).length).toBe(2);
    expect(screen.getByText("Build API")).toBeInTheDocument();
  });

  it("renders a badge and extra fields when mapped", () => {
    render(
      <Kanban
        data={tasks}
        groupBy="status"
        cardBadge="priority"
        cardFields={[{ field: "assignee", label: "Assignee" }]}
      />,
    );
    expect(screen.getByText("High")).toBeInTheDocument();
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
  });

  it("renders cards as nav links when cardHref is given", () => {
    render(<Kanban data={tasks} groupBy="status" cardHref="/tasks/{id}" />);
    const link = screen.getByTestId("kanban-card-2") as HTMLAnchorElement;
    expect(link.tagName).toBe("A");
    expect(link.getAttribute("data-nav-trigger")).toBe("/tasks/2");
  });

  it("fires onCardMove when a card is moved right", () => {
    const onCardMove = vi.fn();
    render(
      <Kanban
        data={tasks}
        groupBy="status"
        columnOrder={["todo", "in_progress", "done"]}
        onCardMove={onCardMove}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /move Design schema right/i }));
    expect(onCardMove).toHaveBeenCalledWith("1", "todo", "in_progress");
  });

  it("shows an empty state when there is no data", () => {
    render(<Kanban data={[]} groupBy="status" emptyText="Nothing here" />);
    expect(screen.getByText("Nothing here")).toBeInTheDocument();
  });
});
