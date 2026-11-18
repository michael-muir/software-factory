import { describe, expect, it } from "vitest";

import { add, clamp, isPositive } from "./calc";

describe("calc", () => {
  it("adds", () => {
    expect(add(2, 3)).toBe(5);
    expect(add(-2, 2)).toBe(0);
  });

  it("knows positive numbers", () => {
    expect(isPositive(1)).toBe(true);
    expect(isPositive(0)).toBe(false);
    expect(isPositive(-1)).toBe(false);
  });

  it("clamps", () => {
    expect(clamp(5, 0, 10)).toBe(5);
    expect(clamp(-1, 0, 10)).toBe(0);
    expect(clamp(11, 0, 10)).toBe(10);
    expect(clamp(0, 0, 10)).toBe(0);
    expect(clamp(10, 0, 10)).toBe(10);
  });
});
