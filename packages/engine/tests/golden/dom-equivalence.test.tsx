import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { Engine, EngineProvider } from "../../src";
import { GOLDEN_FIXTURES } from "./fixtures";
import { extractStructure, normaliseHtml } from "./normaliseDom";

function renderJit(fixture: any): string {
  const { container } = render(
    <EngineProvider designSpec={fixture.designSpec}>
      <Engine schema={fixture.schema} previewData={fixture.previewData} />
    </EngineProvider>
  );
  return container.innerHTML;
}

function renderSsr(fixture: any): string {
  return renderToString(
    <EngineProvider designSpec={fixture.designSpec}>
      <Engine schema={fixture.schema} previewData={fixture.previewData} />
    </EngineProvider>
  );
}

describe("I-1: JIT vs SSR DOM equivalence", () => {
  for (const [name, fixture] of Object.entries(GOLDEN_FIXTURES)) {
    it(`${name}: JIT and SSR produce the same structural DOM`, () => {
      const jit = renderJit(fixture);
      const ssr = renderSsr(fixture);

      const jitStructure = extractStructure(jit);
      const ssrStructure = extractStructure(ssr);

      // Same tag sequence with same data-node-ids
      expect(jitStructure).toEqual(ssrStructure);
    });
  }

  it("renders some content in both modes (sanity)", () => {
    const jit = renderJit(GOLDEN_FIXTURES.minimalText);
    const ssr = renderSsr(GOLDEN_FIXTURES.minimalText);
    expect(jit).toContain("Hello, world");
    expect(ssr).toContain("Hello, world");
  });

  it("preview data interpolation works the same in both modes", () => {
    const jit = renderJit(GOLDEN_FIXTURES.previewBoundText);
    const ssr = renderSsr(GOLDEN_FIXTURES.previewBoundText);
    expect(jit).toContain("Hello, Alex");
    expect(ssr).toContain("Hello, Alex");
  });
});

describe("I-7: same derived view across modes (snapshot)", () => {
  it("normalised HTML for the cardLayout fixture is identical", () => {
    const jit = normaliseHtml(renderJit(GOLDEN_FIXTURES.cardLayout));
    const ssr = normaliseHtml(renderSsr(GOLDEN_FIXTURES.cardLayout));
    expect(jit).toBe(ssr);
  });
});
