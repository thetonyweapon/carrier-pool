import { http, HttpResponse } from "msw";
import { MemoryRouter, useNavigate } from "react-router-dom";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { api, clearAuthToken, setAuthToken } from "./api";
import { candidate, detail, lane, loadList, rate, recs } from "./test/fixtures";
import { server } from "./test/server";

afterEach(() => {
  clearAuthToken();
  vi.restoreAllMocks();
});

function RouteChange({ to }: { to: string }) {
  const navigate = useNavigate();
  return <button onClick={() => navigate(to)}>Change test route</button>;
}

function renderApp(path = "/brokers/broker-a/loads") {
  if (path !== "/brokers") setAuthToken("test-token");
  else clearAuthToken();
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

  it("keeps the queue loading when an aborted request settles after its replacement starts", async () => {
    const pending: Array<{
      resolve: (value: typeof loadList) => void;
      reject: (reason: unknown) => void;
    }> = [];
    vi.spyOn(api, "loads").mockImplementation(() => new Promise((resolve, reject) => {
      pending.push({ resolve, reject });
    }));
    renderApp();
    await waitFor(() => expect(pending).toHaveLength(1));
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "active" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() => expect(pending).toHaveLength(2));

    await act(async () => {
      pending[0].reject(new DOMException("Aborted", "AbortError"));
      await Promise.resolve();
    });
    expect(screen.getByText("Loading queue…")).toBeInTheDocument();

    await act(async () => pending[1].resolve(loadList));
    expect(await screen.findByText("LOAD-001")).toBeInTheDocument();
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

  it("signs in through the demo account flow", async () => {
    renderApp("/brokers");
    expect(await screen.findByRole("heading", { name: "Sign in to operations" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Email or username"), { target: { value: "admin" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "admin" } });
    fireEvent.submit(screen.getByRole("button", { name: "Sign in" }).closest("form")!);
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(await screen.findByRole("heading", { name: "Dispatch board" })).toBeInTheDocument();
  });

  it("shows the locked demo profile and unavailable password reset", async () => {
    renderApp("/profile");
    expect(await screen.findByRole("heading", { name: "Test Operator" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Forgot password?" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText(/not connected in this demo/i)).toBeInTheDocument();
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
    expect(screen.getByText("SHARED")).toBeInTheDocument();
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

  it("reloads candidate details with the new load id after a detail route change", async () => {
    const candidateLoadIds: string[] = [];
    server.use(
      http.get("http://localhost:3000/api/brokers/:broker/loads/:load", ({ params }) =>
        HttpResponse.json({
          ...detail,
          id: params.load,
          display_number: params.load === "load-2" ? "LOAD-002" : "LOAD-001",
        }),
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
      http.get("http://localhost:3000/api/brokers/:broker/carrier-candidates/:candidate", ({ request }) => {
        candidateLoadIds.push(new URL(request.url).searchParams.get("load_id") || "");
        return HttpResponse.json(candidate);
      }),
    );
    setAuthToken("test-token");
    render(
      <MemoryRouter initialEntries={["/brokers/broker-a/loads/load-1?candidate=carrier%3Acarrier-1"]}>
        <App />
        <RouteChange to="/brokers/broker-a/loads/load-2?candidate=carrier%3Acarrier-1" />
      </MemoryRouter>,
    );
    expect(await screen.findByRole("heading", { name: "Lone Star Logistics" })).toBeInTheDocument();
    expect(candidateLoadIds).toEqual(["load-1"]);

    fireEvent.click(screen.getByRole("button", { name: "Change test route" }));
    expect(await screen.findByRole("heading", { name: "LOAD-002" })).toBeInTheDocument();
    await waitFor(() => expect(candidateLoadIds).toContain("load-2"));
    expect(candidateLoadIds[0]).toBe("load-1");
    expect(candidateLoadIds.slice(1).every((loadId) => loadId === "load-2")).toBe(true);
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
