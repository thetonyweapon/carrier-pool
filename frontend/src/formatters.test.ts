import { describe, expect, it } from "vitest";
import { date, day, location, money, percentage } from "./formatters";

describe("formatters", () => {
  it("preserves currency cents and rejects invalid values", () => {
    expect(money("1234.56")).toBe("$1,234.56");
    expect(money("0.00")).toBe("$0.00");
    expect(money("not-a-number")).toBe("—");
    expect(money(null)).toBe("—");
  });

  it("formats date-only values in UTC and invalid values safely", () => {
    expect(date("2026-07-16")).toContain("Jul 16, 2026");
    expect(day("2026-07-16")).toContain("Jul 16, 2026");
    expect(date("invalid")).toBe("—");
    expect(day("invalid")).toBe("—");
  });

  it("formats locations and margin percentages safely", () => {
    expect(location({ city: "Dallas", state: "TX" })).toBe("Dallas, TX");
    expect(location(null)).toBe("—");
    expect(percentage("500.00", "2500.00")).toBe("20.0%");
    expect(percentage("0.00", "0.00")).toBe("—");
  });
});
