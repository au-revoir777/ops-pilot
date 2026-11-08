import { matchWords } from "@/components/layout/command-palette";

describe("command palette matching", () => {
  it("matches typed words against word starts", () => {
    expect(matchWords("palette Ocean", "ocean")).toBe(1);
    expect(matchWords("go System Status", "system stat")).toBe(1);
    expect(matchWords("inject incident lab", "inject")).toBe(1);
    expect(matchWords("anything", "")).toBe(1);
  });

  it("does not fuzzy-match scattered letters", () => {
    // "c-o-rrelati-o-n" contains o, c, e, a, n in order; it must not match "ocean".
    expect(matchWords("copy correlation id", "ocean")).toBe(0);
    expect(matchWords("go Dashboard", "inject")).toBe(0);
  });
});
