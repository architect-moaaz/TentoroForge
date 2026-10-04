import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import React from "react";
import { Table } from "../src/components/Table/Table";

const cell = (photo: string) =>
  render(<Table columns={[{ key: "photo", label: "Photo", format: "image" }]} rows={[{ id: "1", photo }]} />);

describe("a photo value with a malformed credit", () => {
  it("renders the thumbnail without the credit instead of throwing", () => {
    for (const bad of ["%E0%A4%A", "%", "%%", "%zz", ""]) {
      const { container } = cell(`https://images.unsplash.com/x.jpg#credit=${bad}`);
      const img = container.querySelector("img");
      expect(img?.getAttribute("src")).toBe("https://images.unsplash.com/x.jpg");
    }
  });
  it("a good credit still becomes the tooltip", () => {
    const { container } = cell("https://images.unsplash.com/x.jpg#credit=Ann%20Lee&credit_link=https%3A%2F%2Fu%2Fann");
    expect(container.querySelector("img")?.getAttribute("title")).toBe("Photo by Ann Lee on Unsplash");
  });
});
