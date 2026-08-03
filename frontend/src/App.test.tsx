import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { App } from "./App";
import { candidate, detail, lane, loadList, rate, recs } from "./test/fixtures";
import { server } from "./test/server";

function renderApp(path = "/brokers/broker-a/loads") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

describe("operations UI", () => {
  it("loads the default queue without sending empty enum filters", async () => {
    const requests: URL[] = [];
    server.use(
      http.get("http://localhost:3000/api/brokers/:broker/loads", ({ request }) => {
        const url = new URL(request.url);
        requests.push(url);
        if (url.searchParams.has("status") || url.searchParams.has("equipment") || url.searchParams.has("assignment_state")) {
          return HttpResponse.json({ detail: [{ msg: "invalid empty enum" }] }, { status: 422 });
        }
        return HttpResponse.json(loadList);
      }),
    );
    renderApp();
    expect(await screen.findByText("LOAD-001")).toBeInTheDocument();
    expect(requests).toHaveLength(1);
    expect(requests[0].search).toBe("?page=1&page_size=25");
    expect(screen.queryByText("Could not load this panel")).not.toBeInTheDocument();
  });

  it("omits cleared filters after applying them", async () => {
    const requests: URL[] = [];
    server.use(
      http.get("http://localhost:3000/api/brokers/:broker/loads", ({ request }) => {
        requests.push(new URL(request.url));
        return HttpResponse.json(loadList);
      }),
    );
    renderApp();
    await screen.findByText("LOAD-001");
    const status = screen.getByLabelText("Status");
    fireEvent.change(status, { target: { value: "active" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() => expect(requests.length).toBe(2));
    expect(requests[1].searchParams.get("status")).toBe("active");
    fireEvent.change(status, { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() => expect(requests.length).toBe(3));
    expect(requests[2].searchParams.has("status")).toBe(false);
    expect(screen.getByText("LOAD-001")).toBeInTheDocument();
  });

  it("shows the active broker in the shell switcher", async () => {
    server.use(
      http.get("http://localhost:3000/api/brokers/:broker/loads", () =>
        HttpResponse.json(loadList),
      ),
    );
    renderApp("/brokers/broker-b/loads");
    const selector = await screen.findByRole("combobox", { name: "Select broker" });
    expect(selector).toHaveValue("broker-b");
  });

  it("does not show a false empty state while brokers are loading", async () => {
    let release: (() => void) | undefined;
    server.use(
      http.get("http://localhost:3000/api/demo/brokers", () =>
        new Promise((resolve) => {
          release = () => resolve(HttpResponse.json([]));
        }),
      ),
    );
    renderApp("/brokers");
    expect(screen.getByText("Loading demo brokers…")).toBeInTheDocument();
    expect(screen.queryByText("No demo brokers are available.")).not.toBeInTheDocument();
    release?.();
  });

  it("renders detail analytics and an accessible candidate drawer", async () => {
    let assignmentBody: Record<string, unknown> | undefined;
    server.use(
      http.get("http://localhost:3000/api/brokers/:broker/loads/:load", () =>
        HttpResponse.json(detail),
      ),
      http.get("http://localhost:3000/api/brokers/:broker/loads/:load/lane-intelligence", () =>
        HttpResponse.json(lane),
      ),
      http.get("http://localhost:3000/api/brokers/:broker/loads/:load/carrier-rate-estimate", () =>
        HttpResponse.json(rate),
      ),
      http.get("http://localhost:3000/api/brokers/:broker/loads/:load/carrier-recommendations", () =>
        HttpResponse.json(recs),
      ),
      http.get("http://localhost:3000/api/brokers/:broker/carrier-candidates/:candidate", () =>
        HttpResponse.json(candidate),
      ),
      http.post("http://localhost:3000/api/brokers/:broker/loads/:load/assignments", async ({ request }) => {
        assignmentBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({
          state: "assigned",
          carrier: candidate.carriers[0],
          candidate_id: candidate.candidate_id,
          assignment_version: 1,
          assigned_at: "2026-07-16T12:00:00Z",
          broker_id: "broker-a",
          load_id: "load-1",
        });
      }),
    );
    renderApp("/brokers/broker-a/loads/load-1?candidate=carrier%3Acarrier-1");
    expect(await screen.findByRole("heading", { name: "LOAD-001" })).toBeInTheDocument();
    expect(await screen.findByText("Dallas, TX")).toBeInTheDocument();
    expect(await screen.findByText("Lone Star Transport")).toBeInTheDocument();
    expect(screen.getByText("SHARED / exact")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "SHARED POOL ON" })).toBeInTheDocument();
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Lone Star Logistics" })).toBeInTheDocument();
    expect(screen.getByText(/Dallas, TX 75201/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close carrier details" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Assign overlay to this carrier" }));
    await waitFor(() => expect(assignmentBody).toMatchObject({
      carrier_id: "carrier-1",
      candidate_id: "carrier:carrier-1",
      expected_assignment_version: 0,
    }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("shows readable panel errors and successful unavailable rates", async () => {
    server.use(
      http.get("http://localhost:3000/api/brokers/:broker/loads/:load", () =>
        HttpResponse.json(detail),
      ),
      http.get("http://localhost:3000/api/brokers/:broker/loads/:load/lane-intelligence", () =>
        HttpResponse.json({ detail: [{ msg: "lane unavailable" }] }, { status: 422 }),
      ),
      http.get("http://localhost:3000/api/brokers/:broker/loads/:load/carrier-rate-estimate", () =>
        HttpResponse.json({ status: "unavailable", estimate: {}, confidence: { level: "none", data_sufficiency: "insufficient", reasons: [] }, population: { sample_size: 0, source_types: [] } }),
      ),
      http.get("http://localhost:3000/api/brokers/:broker/loads/:load/carrier-recommendations", () =>
        HttpResponse.json(recs),
      ),
    );
    renderApp("/brokers/broker-a/loads/load-1");
    expect(await screen.findByText("Not available for this load")).toBeInTheDocument();
    expect(await screen.findByText("Rate estimate unavailable for this load.")).toBeInTheDocument();
  });

  it("updates the authenticated shared-pool policy from the shell", async () => {
    server.use(
      http.put("http://localhost:3000/api/brokers/:broker/shared-pool-policy", () =>
        HttpResponse.json({
          broker_id: "broker-a",
          enabled: false,
          policy_revision: 2,
          attribute_profile: "public-carrier-name-v1",
        }),
      ),
    );
    renderApp();
    const toggle = await screen.findByRole("button", { name: "SHARED POOL ON" });
    fireEvent.click(toggle);
    expect(await screen.findByRole("button", { name: "SHARED POOL OFF" })).toBeInTheDocument();
  });
});
