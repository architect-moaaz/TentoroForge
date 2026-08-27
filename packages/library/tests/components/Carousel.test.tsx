import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Carousel } from "../../src/components/Carousel/Carousel";
import { CarouselProps } from "../../src/components/Carousel/Carousel.schema";

const items = [
  { title: "Slide One",   caption: "first"  },
  { title: "Slide Two",   caption: "second" },
  { title: "Slide Three", caption: "third"  },
];

describe("Carousel", () => {
  it("shows the first slide active initially", () => {
    render(<Carousel items={items} />);
    expect(screen.getByTestId("carousel-active")).toHaveTextContent("Slide One");
  });

  it("advances to the next slide on next-button click", () => {
    render(<Carousel items={items} />);
    fireEvent.click(screen.getByRole("button", { name: /next/i }));
    expect(screen.getByTestId("carousel-active")).toHaveTextContent("Slide Two");
  });

  it("wraps from the last slide back to the first", () => {
    render(<Carousel items={items} />);
    fireEvent.click(screen.getByRole("button", { name: /previous/i }));
    expect(screen.getByTestId("carousel-active")).toHaveTextContent("Slide Three");
  });

  it("jumps to a slide when its dot is clicked", () => {
    render(<Carousel items={items} />);
    fireEvent.click(screen.getByRole("button", { name: /go to slide 3/i }));
    expect(screen.getByTestId("carousel-active")).toHaveTextContent("Slide Three");
  });

  it("validates props", () => {
    expect(() => CarouselProps.parse({ items })).not.toThrow();
    expect(() => CarouselProps.parse({})).not.toThrow();
  });
});
