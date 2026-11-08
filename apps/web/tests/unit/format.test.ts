import { formatAge, formatConfidence, formatMs, formatPercent, formatRate, humanize, MISSING } from "@/lib/format";

describe("formatters", () => {
  it("formats durations across units", () => {
    expect(formatMs(0.4)).toBe("<1 ms");
    expect(formatMs(212.4)).toBe("212 ms");
    expect(formatMs(1800)).toBe("1.80 s");
    expect(formatMs(12_345)).toBe("12.3 s");
    expect(formatMs(125_000)).toBe("2m 5s");
  });

  it("never renders a missing value as zero", () => {
    for (const fn of [formatMs, formatPercent, formatRate, formatConfidence]) {
      expect(fn(null)).toBe(MISSING);
      expect(fn(undefined)).toBe(MISSING);
      expect(fn(Number.NaN)).toBe(MISSING);
    }
  });

  it("formats ratios, rates and confidence", () => {
    expect(formatPercent(0.5)).toBe("50.0%");
    expect(formatPercent(0)).toBe("0.0%");
    expect(formatPercent(0.0004)).toBe("<0.1%");
    expect(formatRate(3.21)).toBe("3.21 req/s");
    expect(formatConfidence(0.949)).toBe("95%");
  });

  it("formats ages relative to now", () => {
    const now = new Date("2026-11-08T12:00:00Z");
    expect(formatAge("2026-11-08T11:59:30Z", now)).toBe("30s ago");
    expect(formatAge("2026-11-08T11:15:00Z", now)).toBe("45m ago");
    expect(formatAge("2026-11-06T12:00:00Z", now)).toBe("2d ago");
    expect(formatAge("not a date", now)).toBe(MISSING);
  });

  it("humanizes rule identifiers", () => {
    expect(humanize("deployment_db_regression")).toBe("Deployment db regression");
    expect(humanize(null)).toBe(MISSING);
  });
});
