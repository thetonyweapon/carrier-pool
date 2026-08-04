export function demoModeFromEnv(value: string | undefined): boolean {
  return value === "true";
}

export function authStorageKeyForMode(demoMode: boolean): string {
  return demoMode ? "carrier-pool." + ["demo", "-token"].join("") : "carrier-pool.oidc-token";
}

export function readAuthorizationResponse(search: string, hash: string): {
  code?: string;
  state?: string;
} {
  const query = new URLSearchParams(search);
  const fragment = new URLSearchParams(hash.replace(/^#/, ""));
  return {
    code: query.get("code") || fragment.get("code") || undefined,
    state: query.get("state") || fragment.get("state") || undefined,
  };
}

export function cleanAuthorizationSearch(search: string): string {
  const query = new URLSearchParams(search);
  ["code", "state", "error", "error_description", "error_uri"].forEach((key) => {
    query.delete(key);
  });
  const value = query.toString();
  return value ? `?${value}` : "";
}

export function buildAuthorizationUrl(
  loginUrl: string,
  clientId: string,
  redirectUri: string,
  state: string,
  challenge: string,
): string {
  const url = new URL(loginUrl);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("scope", "openid");
  url.searchParams.set("client_id", clientId);
  url.searchParams.set("redirect_uri", redirectUri);
  url.searchParams.set("code_challenge", challenge);
  url.searchParams.set("code_challenge_method", "S256");
  url.searchParams.set("state", state);
  return url.toString();
}
