export type Summary = { id: string; name: string };
export type DemoBroker = Summary & { is_demo: boolean };
export type Carrier = {
  id: string;
  name: string;
  mc_number?: string | null;
  dot_number?: string | null;
  phone_number?: string | null;
};
export type Location = { city: string; state: string; postal_code: string };
export type Freshness = { last_synced_at: string; age_seconds: number };
export type Assignment = {
  state: string;
  carrier?: Carrier | null;
  candidate_id?: string | null;
  assignment_version: number;
  assigned_at?: string | null;
};
export type Load = {
  id: string;
  display_number: string;
  status: string;
  equipment_type: string;
  weight_lbs?: string | null;
  distance_miles?: string | null;
  customer: Summary;
  source: Summary;
  carrier?: Carrier | null;
  origin?: Location | null;
  destination?: Location | null;
  next_schedule?: string | null;
  customer_rate?: string | null;
  carrier_rate?: string | null;
  margin?: string | null;
  freshness: Freshness;
  assignment: Assignment;
};
export type Stop = {
  id: string;
  sequence_number: number;
  stop_type: string;
  city: string;
  state: string;
  postal_code: string;
  scheduled_date?: string | null;
  scheduled_start_at?: string | null;
  scheduled_end_at?: string | null;
  actual_arrived_at?: string | null;
  actual_departed_at?: string | null;
  location_name?: string | null;
};
export type Detail = Load & { stops: Stop[] };
export type LoadListResponse = {
  broker_id: string;
  items: Load[];
  page: number;
  page_size: number;
  total: number;
};
export type Lane = {
  broker_id: string;
  load_id: string;
  lane: {
    exact_key: string;
    metro_key?: string | null;
    origin: { exact_key: string; metro_name?: string | null };
    destination: { exact_key: string; metro_name?: string | null };
  };
  history: {
    exact_count: number;
    nearby_count: number;
    equipment_exact_count: number;
    equipment_nearby_count: number;
    selected_scope: string;
    data_sufficiency: string;
    fallback_reason?: string | null;
    history_limit: number;
    history_truncated: boolean;
  };
  typical_travel_time?: { minutes: number; label: string; version: string } | null;
};
export type Rate = {
  status: string;
  estimate: {
    amount?: string | null;
    low?: string | null;
    high?: string | null;
    calculation_mode?: string | null;
  };
  confidence: { level: string; data_sufficiency: string; reasons: string[] };
  population: {
    sample_size: number;
    selected_tier?: string | null;
    lookback_days?: number | null;
    source_types: string[];
  };
};
export type Recommendation = {
  rank: number;
  candidate_id: string;
  name: string;
  score: number;
  data_sufficiency: string;
  factors: {
    code: string;
    evidence_count: number;
    contribution: number;
    explanation: string;
  }[];
};
export type UnscoredCarrier = { candidate_id: string; name: string; reason: string };
export type Recs = {
  recommendations: Recommendation[];
  unscored_carriers: UnscoredCarrier[];
};
export type SharedRecommendation = {
  scope: "shared";
  rank: number;
  candidate_id: string;
  name: string;
  match_quality: string;
  equipment_type: string;
  evidence_count_bucket: string;
  contributing_broker_count_bucket: string;
};
export type SharedRecs = {
  broker_id: string;
  load_id: string;
  policy_version: string;
  policy_revision: number;
  scoring_version: string;
  normalization_version: string;
  recommendations: SharedRecommendation[];
};
export type SharedRate = {
  scope: "shared";
  broker_id: string;
  load_id: string;
  policy_version: string;
  policy_revision: number;
  estimation_version: string;
  normalization_version: string;
  status: string;
  estimate: {
    amount?: string | null;
    low?: string | null;
    high?: string | null;
    calculation_mode?: string | null;
  };
  confidence: string;
  match_scope?: string | null;
  equipment_scope?: string | null;
  sample_count_bucket: string;
  contributing_broker_count_bucket: string;
  selected_tier?: string | null;
  lookback_days?: number | null;
};
export type SharedPolicy = {
  broker_id: string;
  enabled: boolean;
  policy_revision: number;
  attribute_profile?: string | null;
};
export type CandidateMember = Carrier & {
  source_id: string;
  home_city?: string | null;
  home_state?: string | null;
};
export type Candidate = {
  candidate_id: string;
  name: string;
  mc_number?: string | null;
  dot_number?: string | null;
  carriers: CandidateMember[];
  evidence: {
    origin: Location;
    destination: Location;
    completed_month?: string | null;
    outcome: string;
  }[];
};
export type Profile = {
  account_id: string;
  email?: string | null;
  name: string;
  broker_id: string;
  broker_name: string;
  is_admin: boolean;
  is_demo: boolean;
  profile_locked: boolean;
};

const base =
  import.meta.env.VITE_API_BASE_URL ||
  (typeof window !== "undefined" ? `${window.location.origin}/api` : "/api");
const authStorageKey = "carrier-pool.demo-token";

export class ApiError extends Error {
  status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function errorMessage(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === "object" && item !== null && "msg" in item) {
          return String((item as { msg: unknown }).msg);
        }
        return JSON.stringify(item);
      })
      .join(", ");
  }
  return detail == null ? "Request failed" : JSON.stringify(detail);
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  const token = typeof window !== "undefined" ? window.sessionStorage.getItem(authStorageKey) : null;
  if (token && !headers.has("Authorization")) headers.set("Authorization", `Bearer ${token}`);
  if (typeof options.body === "string" && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${base}${path}`, { ...options, headers });
  if (!response.ok) {
    let detail: unknown;
    try {
      detail = (await response.json()).detail;
    } catch {
      detail = undefined;
    }
    throw new ApiError(errorMessage(detail), response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function setAuthToken(token: string): void {
  if (typeof window !== "undefined") window.sessionStorage.setItem(authStorageKey, token);
}

export function clearAuthToken(): void {
  if (typeof window !== "undefined") window.sessionStorage.removeItem(authStorageKey);
}

export function hasAuthToken(): boolean {
  return typeof window !== "undefined" && window.sessionStorage.getItem(authStorageKey) !== null;
}

const segment = (value: string) => encodeURIComponent(value);

export const api = {
  brokers: (signal?: AbortSignal) => request<DemoBroker[]>("/demo/brokers", { signal }),
  demoAuth: (broker: string, identifier: string, password: string, signal?: AbortSignal) =>
    request<{ access_token: string; token_type: string; broker_id: string; account_id: string; is_admin: boolean }>("/demo/auth", {
      method: "POST",
      body: JSON.stringify({ broker_id: broker, identifier, password }),
      signal,
    }),
  createAccount: (broker: string, name: string, email: string, password: string) =>
    request<{ account_id: string; broker_id: string; email: string; name: string }>("/demo/accounts", {
      method: "POST",
      body: JSON.stringify({ broker_id: broker, name, email, password }),
    }),
  me: (broker?: string, signal?: AbortSignal) =>
    request<Profile>(broker ? `/me?broker_id=${segment(broker)}` : "/me", { signal }),
  updateProfile: (body: { name?: string; email?: string; password?: string }) =>
    request<Profile>("/me", { method: "PATCH", body: JSON.stringify(body) }),
  sharedPolicy: (broker: string, signal?: AbortSignal) =>
    request<SharedPolicy>(`/brokers/${segment(broker)}/shared-pool-policy`, { signal }),
  updateSharedPolicy: (broker: string, enabled: boolean) =>
    request<SharedPolicy>(`/brokers/${segment(broker)}/shared-pool-policy`, {
      method: "PUT",
      body: JSON.stringify({ enabled }),
    }),
  loads: (broker: string, query: string, signal?: AbortSignal) =>
    request<LoadListResponse>(`/brokers/${segment(broker)}/loads?${query}`, { signal }),
  detail: (broker: string, load: string, signal?: AbortSignal) =>
    request<Detail>(`/brokers/${segment(broker)}/loads/${segment(load)}`, { signal }),
  lane: (broker: string, load: string, signal?: AbortSignal) =>
    request<Lane>(`/brokers/${segment(broker)}/loads/${segment(load)}/lane-intelligence`, {
      signal,
    }),
  rate: (broker: string, load: string, signal?: AbortSignal) =>
    request<Rate>(`/brokers/${segment(broker)}/loads/${segment(load)}/carrier-rate-estimate`, {
      signal,
    }),
  recs: (broker: string, load: string, signal?: AbortSignal) =>
    request<Recs>(
      `/brokers/${segment(broker)}/loads/${segment(load)}/carrier-recommendations?limit=20`,
      { signal },
    ),
  sharedRecs: (broker: string, load: string, signal?: AbortSignal) =>
    request<SharedRecs>(
      `/brokers/${segment(broker)}/loads/${segment(load)}/shared-carrier-recommendations`,
      { signal },
    ),
  sharedRate: (broker: string, load: string, signal?: AbortSignal) =>
    request<SharedRate>(
      `/brokers/${segment(broker)}/loads/${segment(load)}/shared-carrier-rate-estimate`,
      { signal },
    ),
  candidate: (broker: string, load: string, candidate: string, signal?: AbortSignal) =>
    request<Candidate>(
      `/brokers/${segment(broker)}/carrier-candidates/${segment(candidate)}?load_id=${segment(load)}`,
      { signal },
    ),
  assign: (broker: string, load: string, body: object) =>
    request<Assignment>(`/brokers/${segment(broker)}/loads/${segment(load)}/assignments`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
