import { describe, it, expect } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { Lightbox } from "../../src/components/Lightbox/Lightbox";
import { LightboxProps } from "../../src/components/Lightbox/Lightbox.schema";

const images = [
  { src: "/a.jpg", alt: "Gate A" },
  { src: "/b.jpg", alt: "Gate B" },
  { src: "/c.jpg", alt: "Gate C" },
];

describe("Lightbox", () => {
  it("renders a thumbnail per image and no overlay initially", () => {
    render(<Lightbox images={images} />);
    expect(screen.getByRole("button", { name: /open Gate A/i })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
  });
  it("opens the overlay on the clicked image and can navigate next", () => {
    render(<Lightbox images={images} />);
    fireEvent.click(screen.getByRole("button", { name: /open Gate A/i }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByRole("img", { name: "Gate A" })).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: /next/i }));
    expect(within(dialog).getByRole("img", { name: "Gate B" })).toBeInTheDocument();
  });
  it("closes the overlay", () => {
    render(<Lightbox images={images} />);
    fireEvent.click(screen.getByRole("button", { name: /open Gate A/i }));
    fireEvent.click(screen.getByRole("button", { name: /close/i }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
  it("validates props", () => {
    expect(() => LightboxProps.parse({ images })).not.toThrow();
    expect(() => LightboxProps.parse({})).not.toThrow();
  });
});
