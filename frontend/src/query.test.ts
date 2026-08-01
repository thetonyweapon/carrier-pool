import { describe, expect, it } from "vitest";
import {
  buildQueueSearchParams,
  EMPTY_QUEUE_FILTERS,
  parsePage,
  parseQueueSearchParams,
} from "./query";

describe("queue query state", () => {
  it("omits empty optional filters", () => {
    const params = buildQueueSearchParams(EMPTY_QUEUE_FILTERS, 1);
    expect(params.toString()).toBe("page=1");
    expect(params.has("status")).toBe(false);
    expect(params.has("equipment")).toBe(false);
    expect(params.has("assignment_state")).toBe(false);
  });

  it("serializes selected filters and trims search", () => {
    const params = buildQueueSearchParams(
      { search: "  LOAD-1 ", status: "active", equipment: "reefer", assignment_state: "unassigned" },
      2,
    );
    expect(params.get("search")).toBe("LOAD-1");
    expect(params.get("status")).toBe("active");
    expect(params.get("equipment")).toBe("reefer");
    expect(params.get("assignment_state")).toBe("unassigned");
    expect(params.get("page")).toBe("2");
  });

  it("normalizes malformed pages", () => {
    expect(parsePage("0")).toBe(1);
    expect(parsePage("-3")).toBe(1);
    expect(parsePage("2.5")).toBe(1);
    expect(parsePage("not-a-page")).toBe(1);
    expect(parseQueueSearchParams(new URLSearchParams("page=3")).page).toBe(3);
  });
});
