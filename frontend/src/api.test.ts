import { describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "./test/server";
import { api, ApiError } from "./api";

describe("api client", () => {
  it("turns validation arrays into readable errors", async () => {
    server.use(
      http.get("http://localhost:3000/api/brokers/broker-a/loads", () =>
        HttpResponse.json({ detail: [{ msg: "Input should be a valid enum member" }] }, { status: 422 }),
      ),
    );
    await expect(api.loads("broker-a", "status=")).rejects.toMatchObject({
      status: 422,
      message: "Input should be a valid enum member",
    });
  });

  it("encodes broker and load path segments", async () => {
    let requested = "";
    server.use(
      http.get("http://localhost:3000/api/brokers/:broker/loads/:load", ({ request }) => {
        requested = new URL(request.url).pathname;
        return HttpResponse.json({});
      }),
    );
    await api.detail("broker/a", "load one");
    expect(requested).toBe("/api/brokers/broker%2Fa/loads/load%20one");
  });

  it("supports abort signals", async () => {
    const controller = new AbortController();
    controller.abort();
    await expect(api.brokers(controller.signal)).rejects.toBeDefined();
  });

  it("exposes structured API errors", async () => {
    server.use(
      http.get("http://localhost:3000/api/demo/brokers", () =>
        HttpResponse.text("server exploded", { status: 500 }),
      ),
    );
    await expect(api.brokers()).rejects.toBeInstanceOf(ApiError);
  });
});
