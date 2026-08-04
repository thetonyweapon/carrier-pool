import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { api } from "./api";

describe("production authentication shell", () => {
  afterEach(() => {
    window.history.replaceState({}, document.title, "/");
    window.sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it("does not render demo access when built for production", () => {
    render(
      <MemoryRouter initialEntries={["/login"]}>
        <App />
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { name: "Sign in to operations" })).toBeInTheDocument();
    expect(screen.queryByText("DEMO MODE")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /organization sign-in/i })).toHaveAttribute(
      "href",
      "https://issuer.example/authorize",
    );
  });

  it("clears invalid callback state without exchanging a mismatched code", async () => {
    window.sessionStorage.setItem("carrier-pool.oidc-state", "expected");
    window.sessionStorage.setItem("carrier-pool.oidc-verifier", "verifier");
    window.history.replaceState({}, document.title, "/login?code=secret&state=wrong");
    const exchange = vi.spyOn(api, "exchangeOidcCode");

    render(<MemoryRouter initialEntries={["/login"]}><App /></MemoryRouter>);

    await waitFor(() => {
      expect(window.sessionStorage.getItem("carrier-pool.oidc-state")).toBeNull();
      expect(window.sessionStorage.getItem("carrier-pool.oidc-verifier")).toBeNull();
    });
    expect(exchange).not.toHaveBeenCalled();
  });

  it("clears callback state when token exchange fails", async () => {
    window.sessionStorage.setItem("carrier-pool.oidc-state", "expected");
    window.sessionStorage.setItem("carrier-pool.oidc-verifier", "verifier");
    window.history.replaceState({}, document.title, "/login?code=secret&state=expected");
    const exchange = vi.spyOn(api, "exchangeOidcCode").mockRejectedValue(new Error("offline"));

    render(<MemoryRouter initialEntries={["/login"]}><App /></MemoryRouter>);

    await waitFor(() => expect(exchange).toHaveBeenCalledWith("secret", "verifier"));
    expect(window.sessionStorage.getItem("carrier-pool.oidc-state")).toBeNull();
    expect(window.sessionStorage.getItem("carrier-pool.oidc-verifier")).toBeNull();
  });

  it("exchanges a valid callback, stores the token, and clears the URL", async () => {
    window.sessionStorage.setItem("carrier-pool.oidc-state", "expected");
    window.sessionStorage.setItem("carrier-pool.oidc-verifier", "verifier");
    window.history.replaceState({}, document.title, "/login?code=secret&state=expected");
    const exchange = vi.spyOn(api, "exchangeOidcCode").mockResolvedValue({
      access_token: "provider-token",
      token_type: "Bearer",
    });

    render(<MemoryRouter initialEntries={["/login"]}><App /></MemoryRouter>);

    await waitFor(() => {
      expect(exchange).toHaveBeenCalledWith("secret", "verifier");
      expect(window.sessionStorage.getItem("carrier-pool.oidc-token")).toBe("provider-token");
      expect(window.sessionStorage.getItem("carrier-pool.oidc-state")).toBeNull();
      expect(window.sessionStorage.getItem("carrier-pool.oidc-verifier")).toBeNull();
      expect(window.location.search).toBe("");
    });
  });

  it("exchanges a valid fragment callback", async () => {
    window.sessionStorage.setItem("carrier-pool.oidc-state", "expected");
    window.sessionStorage.setItem("carrier-pool.oidc-verifier", "verifier");
    window.history.replaceState({}, document.title, "/login#code=secret&state=expected");
    const exchange = vi.spyOn(api, "exchangeOidcCode").mockResolvedValue({
      access_token: "fragment-token",
      token_type: "Bearer",
    });

    render(<MemoryRouter initialEntries={["/login"]}><App /></MemoryRouter>);

    await waitFor(() => {
      expect(exchange).toHaveBeenCalledWith("secret", "verifier");
      expect(window.sessionStorage.getItem("carrier-pool.oidc-token")).toBe("fragment-token");
      expect(window.sessionStorage.getItem("carrier-pool.oidc-state")).toBeNull();
      expect(window.sessionStorage.getItem("carrier-pool.oidc-verifier")).toBeNull();
      expect(window.location.search).toBe("");
      expect(window.location.hash).toBe("");
    });
  });
});
