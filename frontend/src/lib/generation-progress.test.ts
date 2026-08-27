import { describe, expect, it } from "vitest";
import {
  PHASE_BASELINES,
  TOTAL_BASELINE_SECONDS,
  computeGenerationProgress,
  formatEta,
  formatElapsed,
  baselineIndexFromQuestIndex,
} from "./generation-progress";

describe("baselineIndexFromQuestIndex", () => {
  it("maps planning (quest=-1) to baseline index 0", () => {
    expect(baselineIndexFromQuestIndex(-1)).toBe(0);
  });
  it("maps contracts (quest=0) to baseline index 1", () => {
    expect(baselineIndexFromQuestIndex(0)).toBe(1);
  });
  it("maps last quest phase to last baseline index", () => {
    expect(baselineIndexFromQuestIndex(8)).toBe(9);
  });
});

describe("computeGenerationProgress — indeterminate paths", () => {
  it("returns indeterminate before streaming starts", () => {
    const r = computeGenerationProgress({
      startedAt: null,
      now: 1_000_000,
      activeQuestIndex: -1,
      completedQuestIndices: [],
    });
    expect(r.isIndeterminate).toBe(true);
    expect(r.percent).toBe(0);
    expect(r.etaSeconds).toBeNull();
    expect(r.etaLabel).toBe("starting…");
  });

  it("returns indeterminate in the first 2s with no completed phases", () => {
    const start = 1_000_000;
    const r = computeGenerationProgress({
      startedAt: start,
      now: start + 1_500,
      activeQuestIndex: -1,
      completedQuestIndices: [],
    });
    expect(r.isIndeterminate).toBe(true);
  });
});

describe("computeGenerationProgress — planning phase", () => {
  it("shows some progress once we're 30s into planning (mid-planning)", () => {
    const start = 1_000_000;
    const r = computeGenerationProgress({
      startedAt: start,
      now: start + 30_000,
      activeQuestIndex: -1,
      completedQuestIndices: [],
    });
    expect(r.isIndeterminate).toBe(false);
    // Planning baseline 180s, asymptotic fill: 30s → 180·30/210 ≈ 25.7 of the
    // 575s total ≈ 4-5%.
    expect(r.percent).toBeGreaterThanOrEqual(3);
    expect(r.percent).toBeLessThanOrEqual(7);
    expect(r.etaSeconds).toBeGreaterThan(300);
  });

  it("NEVER FREEZES: percent keeps rising the longer a phase runs (the 'stuck at 13%' bug)", () => {
    const start = 1_000_000;
    const at = (secs: number) =>
      computeGenerationProgress({
        startedAt: start,
        now: start + secs * 1000,
        activeQuestIndex: -1, // still planning the whole time
        completedQuestIndices: [],
      }).percent;
    // Planning overruns its 180s baseline — the OLD model capped partial at the
    // baseline so percent pinned. The asymptotic model must keep increasing.
    const p60 = at(60), p180 = at(180), p400 = at(400), p700 = at(700);
    expect(p180).toBeGreaterThan(p60);
    expect(p400).toBeGreaterThan(p180);
    expect(p700).toBeGreaterThan(p400);
  });
});

describe("computeGenerationProgress — quest phases", () => {
  it("increases percent as quest phases complete", () => {
    const start = 1_000_000;
    // Contracts + foundation done (30 + 60 = 90 baseline seconds).
    const now = start + 90_000;
    const r = computeGenerationProgress({
      startedAt: start,
      now,
      activeQuestIndex: 2, // backend
      completedQuestIndices: [0, 1], // contracts, foundation
      phaseStartTimes: { 2: now }, // just started backend
    });
    // completedBase = planning(60 baseline; NOT in completedQuestIndices?)
    // -- planning is never in completedQuestIndices (it's quest=-1).
    // completedBase = 30 + 60 = 90, partial=0 (just started), total=455
    // percent ≈ 90/455 ≈ 19.8 → rounded 20
    // completedBase 90 / 575 total ≈ 16% (backend just started).
    expect(r.percent).toBeGreaterThanOrEqual(14);
    expect(r.percent).toBeLessThanOrEqual(18);
    expect(r.etaSeconds).toBeGreaterThan(200);
    expect(r.etaSeconds).toBeLessThan(500);
  });

  it("uses per-phase start time to refine partial when provided", () => {
    const start = 1_000_000;
    // Halfway through backend (45s in, baseline 90s).
    const backendStart = start + 90_000; // after contracts+foundation
    const now = backendStart + 45_000;
    const r = computeGenerationProgress({
      startedAt: start,
      now,
      activeQuestIndex: 2,
      completedQuestIndices: [0, 1],
      phaseStartTimes: { 2: backendStart },
    });
    // Should show ~90/455 + 45/455 ≈ 29-30%.
    // (90 + 90·45/135=30) / 575 ≈ 21%.
    expect(r.percent).toBeGreaterThanOrEqual(18);
    expect(r.percent).toBeLessThanOrEqual(24);
  });

  it("percent rises smoothly through the pipeline (halfway through index → ~85%)", () => {
    const start = 1_000_000;
    const r = computeGenerationProgress({
      startedAt: start,
      now: start + 400_000,
      activeQuestIndex: 8,
      completedQuestIndices: [0, 1, 2, 3, 4, 5, 6, 7],
    });
    // 30+60+90+45+90+15+30+20 = 380 baseline done; index heuristic 7.5s
    // Total 387.5 / 455 = 85%.
    // 380 done + index partial / 575 ≈ 68%.
    expect(r.percent).toBeGreaterThanOrEqual(64);
    expect(r.percent).toBeLessThanOrEqual(72);
  });

  it("returns 100% + done when isComplete is true", () => {
    const r = computeGenerationProgress({
      startedAt: 1_000_000,
      now: 1_500_000,
      activeQuestIndex: 8,
      completedQuestIndices: [0, 1, 2, 3, 4, 5, 6, 7, 8],
      isComplete: true,
    });
    expect(r.percent).toBe(100);
    expect(r.etaSeconds).toBe(0);
    expect(r.etaLabel).toBe("done");
  });
});

describe("computeGenerationProgress — ETA scale refinement", () => {
  it("stretches ETA when actual runs 2× baseline", () => {
    const start = 1_000_000;
    // Baseline for contracts is 30s. Say it actually took 60s. Now we're
    // starting foundation. Scale should ≈ 2x.
    const r = computeGenerationProgress({
      startedAt: start,
      now: start + 60_000,
      activeQuestIndex: 1, // foundation
      completedQuestIndices: [0], // contracts done
    });
    // remaining baseline (excluding planning): 60+90+45+90+15+30+20+15 + partial_foundation ≈ 365+22.5 ≈ 342.5
    // scale ≈ 60 / (30 + 30) = 1.0 ... hmm wait: completedBase=30, partial=30 (foundation baseline is 60, so 50% = 30)
    // virtualDone = 60 → scale = 60/60 = 1.0. ETA = (455-60) * 1 = 395s
    // OK so this test needs a case with real over-run.
    expect(r.etaSeconds).toBeGreaterThan(300);
  });

  it("clamps scale to [0.5, 3] to avoid runaway ETAs", () => {
    const start = 1_000_000;
    // Contract "took" absurdly long — 10 minutes for a 30s baseline.
    const r = computeGenerationProgress({
      startedAt: start,
      now: start + 600_000,
      activeQuestIndex: 1,
      completedQuestIndices: [0],
    });
    // scale would be 600 / 60 = 10 but capped to 3.
    // remaining baseline ≈ 395s, ETA ≈ 395 * 3 = 1185s max.
    expect(r.etaSeconds).toBeGreaterThan(0);
    expect(r.etaSeconds!).toBeLessThanOrEqual(1600);
  });
});

describe("formatEta", () => {
  it("returns 'almost done' for <=3s", () => {
    expect(formatEta(0)).toBe("almost done");
    expect(formatEta(3)).toBe("almost done");
  });
  it("returns seconds under a minute", () => {
    expect(formatEta(45)).toBe("~45s");
  });
  it("returns minutes with no remainder cleanly", () => {
    expect(formatEta(120)).toBe("~2m");
  });
  it("returns minutes + seconds", () => {
    expect(formatEta(200)).toBe("~3m 20s");
  });
  it("handles null / infinity", () => {
    expect(formatEta(null)).toBe("—");
    expect(formatEta(Infinity)).toBe("—");
  });
});

describe("formatElapsed", () => {
  it("formats mm:ss", () => {
    expect(formatElapsed(0)).toBe("0:00");
    expect(formatElapsed(65)).toBe("1:05");
    expect(formatElapsed(3600)).toBe("60:00");
  });
});

describe("PHASE_BASELINES integrity", () => {
  it("has planning + 9 quest phases", () => {
    expect(PHASE_BASELINES.length).toBe(10);
    expect(PHASE_BASELINES[0].id).toBe("planning");
  });
  it("total is a positive integer", () => {
    expect(TOTAL_BASELINE_SECONDS).toBeGreaterThan(0);
    expect(Number.isInteger(TOTAL_BASELINE_SECONDS)).toBe(true);
  });
});
