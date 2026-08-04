import { describe, expect, it } from "vitest";
import {
  authStorageKeyForMode,
  buildAuthorizationUrl,
  cleanAuthorizationSearch,
  demoModeFromEnv,
  readAuthorizationResponse,
} from "./oidc";

describe("OIDC boundary helpers", () => {
  it("fails closed when the demo build flag is unset", () => {
    expect(demoModeFromEnv(undefined)).toBe(false);
    expect(authStorageKeyForMode(false)).toBe("carrier-pool.oidc-token");
    expect(authStorageKeyForMode(true)).toBe("carrier-pool.demo-token");
  });

  it("reads query and fragment authorization responses", () => {
    expect(readAuthorizationResponse("?code=query-code&state=query-state", "")).toEqual({
      code: "query-code",
      state: "query-state",
    });
    expect(readAuthorizationResponse("", "#code=fragment-code&state=fragment-state")).toEqual({
      code: "fragment-code",
      state: "fragment-state",
    });
  });

  it("builds a PKCE authorization request and removes callback secrets", () => {
    const url = new URL(
      buildAuthorizationUrl(
        "https://issuer.example/authorize",
        "carrier-pool",
        "https://app.example.com/login",
        "state-value",
        "challenge-value",
      ),
    );
    expect(url.searchParams.get("response_type")).toBe("code");
    expect(url.searchParams.get("scope")).toBe("openid");
    expect(url.searchParams.get("code_challenge_method")).toBe("S256");
    expect(cleanAuthorizationSearch("?code=secret&state=state&next=loads")).toBe("?next=loads");
  });
});
