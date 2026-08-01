export type Summary = { id: string; name: string };
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
  };
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
};

const base =
  import.meta.env.VITE_API_BASE_URL ||
  (typeof window !== "undefined" ? `${window.location.origin}/api` : "/api");

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

const segment = (value: string) => encodeURIComponent(value);

export const api = {
  brokers: (signal?: AbortSignal) => request<Summary[]>("/demo/brokers", { signal }),
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
  candidate: (broker: string, candidate: string, signal?: AbortSignal) =>
    request<Candidate>(`/brokers/${segment(broker)}/carrier-candidates/${segment(candidate)}`, {
      signal,
    }),
  assign: (broker: string, load: string, body: object) =>
    request<Assignment>(`/brokers/${segment(broker)}/loads/${segment(load)}/assignments`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
