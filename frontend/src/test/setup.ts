import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll } from "vitest";
import { server } from "./server";

const nativeFetch = globalThis.fetch;

beforeAll(() => {
  globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    const absolute = typeof input === "string" && input.startsWith("/")
      ? new URL(input, "http://localhost").toString()
      : input;
    return nativeFetch(absolute, init);
  }) as typeof fetch;
  server.listen({ onUnhandledRequest: "error" });
});

afterEach(() => {
  cleanup();
  server.resetHandlers();
});

afterAll(() => {
  server.close();
  globalThis.fetch = nativeFetch;
});
