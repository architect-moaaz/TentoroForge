// packages/library/tests/components/Accordion.test.tsx
import { describe, it, expect } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import { Accordion } from "../../src/components/Accordion/Accordion";
import { AccordionPanel } from "../../src/components/Accordion/AccordionPanel";

describe("Accordion", () => {
  it("renders panel labels + bodies", () => {
    const { getByText } = render(
      <Accordion mode="single">
        <AccordionPanel value="a" label="Alpha"><span>body-a</span></AccordionPanel>
        <AccordionPanel value="b" label="Beta"><span>body-b</span></AccordionPanel>
      </Accordion>
    );
    expect(getByText("Alpha")).toBeTruthy();
    expect(getByText("Beta")).toBeTruthy();
    // Bodies are in DOM but hidden until expanded
    const bodyA = getByText("body-a").closest("[data-accordion-body]") as HTMLElement;
    expect(bodyA?.getAttribute("data-accordion-open")).toBe("false");
  });

  it("expands defaultOpen panels initially", () => {
    const { getByText } = render(
      <Accordion mode="multi" defaultOpen={["a"]}>
        <AccordionPanel value="a" label="A"><span>body-a</span></AccordionPanel>
        <AccordionPanel value="b" label="B"><span>body-b</span></AccordionPanel>
      </Accordion>
    );
    const bodyA = getByText("body-a").closest("[data-accordion-body]") as HTMLElement;
    const bodyB = getByText("body-b").closest("[data-accordion-body]") as HTMLElement;
    expect(bodyA?.getAttribute("data-accordion-open")).toBe("true");
    expect(bodyB?.getAttribute("data-accordion-open")).toBe("false");
  });

  it("toggles panels on header click in single mode (closes others)", () => {
    const { getByText } = render(
      <Accordion mode="single">
        <AccordionPanel value="a" label="Alpha"><span>body-a</span></AccordionPanel>
        <AccordionPanel value="b" label="Beta"><span>body-b</span></AccordionPanel>
      </Accordion>
    );
    fireEvent.click(getByText("Alpha"));
    let bodyA = getByText("body-a").closest("[data-accordion-body]") as HTMLElement;
    expect(bodyA.getAttribute("data-accordion-open")).toBe("true");

    fireEvent.click(getByText("Beta"));
    bodyA = getByText("body-a").closest("[data-accordion-body]") as HTMLElement;
    const bodyB = getByText("body-b").closest("[data-accordion-body]") as HTMLElement;
    expect(bodyA.getAttribute("data-accordion-open")).toBe("false");
    expect(bodyB.getAttribute("data-accordion-open")).toBe("true");
  });

  it("toggles independently in multi mode", () => {
    const { getByText } = render(
      <Accordion mode="multi">
        <AccordionPanel value="a" label="A"><span>body-a</span></AccordionPanel>
        <AccordionPanel value="b" label="B"><span>body-b</span></AccordionPanel>
      </Accordion>
    );
    fireEvent.click(getByText("A"));
    fireEvent.click(getByText("B"));
    const bodyA = getByText("body-a").closest("[data-accordion-body]") as HTMLElement;
    const bodyB = getByText("body-b").closest("[data-accordion-body]") as HTMLElement;
    expect(bodyA.getAttribute("data-accordion-open")).toBe("true");
    expect(bodyB.getAttribute("data-accordion-open")).toBe("true");
  });

  it("applies StyleSlot via resolveStyle", () => {
    const { container } = render(
      <Accordion mode="single" style={{ padding: "tokens.spacing.4" }}>
        <AccordionPanel value="a" label="A"><span>x</span></AccordionPanel>
      </Accordion>
    );
    expect((container.firstChild as HTMLElement).style.padding)
      .toBe("var(--token-spacing-4)");
  });

  it("emits data-motion attribute when motion set", () => {
    const { container } = render(
      <Accordion mode="single" style={{ motion: "slide-in" }}>
        <AccordionPanel value="a" label="A"><span>x</span></AccordionPanel>
      </Accordion>
    );
    expect((container.firstChild as HTMLElement).getAttribute("data-motion"))
      .toBe("slide-in");
  });
});
