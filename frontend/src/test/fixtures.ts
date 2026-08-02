import type { Candidate, Detail, Lane, Load, LoadListResponse, Rate, Recs, SharedRate, SharedRecs, Summary } from "../api";

export const demoBrokers: Summary[] = [
  { id: "broker-a", name: "Ithaca Freight Partners" },
  { id: "broker-b", name: "Aegean Route Logistics" },
  { id: "broker-c", name: "Olive Harbor Transport" },
];

export const load: Load = {
  id: "load-1",
  display_number: "LOAD-001",
  status: "active",
  equipment_type: "dry_van",
  weight_lbs: "42000.0",
  distance_miles: "123.4",
  customer: { id: "customer-1", name: "Gulf Coast Foods" },
  source: { id: "source-a", name: "FreightFlow" },
  carrier: null,
  origin: { city: "Dallas", state: "TX", postal_code: "75201" },
  destination: { city: "Houston", state: "TX", postal_code: "77002" },
  next_schedule: "2026-07-16T17:00:00Z",
  customer_rate: "2450.00",
  carrier_rate: null,
  margin: null,
  freshness: { last_synced_at: "2026-07-16T23:00:00Z", age_seconds: 100 },
  assignment: {
    state: "unassigned",
    carrier: null,
    candidate_id: null,
    assignment_version: 0,
    assigned_at: null,
  },
};

export const loadList: LoadListResponse = {
  broker_id: "broker-a",
  items: [load],
  page: 1,
  page_size: 25,
  total: 1,
};

export const detail: Detail = {
  ...load,
  stops: [
    {
      id: "stop-1",
      sequence_number: 1,
      stop_type: "pickup",
      city: "Dallas",
      state: "TX",
      postal_code: "75201",
      scheduled_date: "2026-07-16",
      scheduled_start_at: null,
      scheduled_end_at: null,
      actual_arrived_at: null,
      actual_departed_at: null,
      location_name: "Origin warehouse",
    },
  ],
};

export const lane: Lane = {
  broker_id: "broker-a",
  load_id: "load-1",
  lane: {
    exact_key: "75201->77002",
    metro_key: "dallas->houston",
    origin: { exact_key: "75201", metro_name: "Dallas" },
    destination: { exact_key: "77002", metro_name: "Houston" },
  },
  history: {
    exact_count: 4,
    nearby_count: 2,
    equipment_exact_count: 3,
    equipment_nearby_count: 1,
    selected_scope: "exact",
    data_sufficiency: "sufficient",
    fallback_reason: null,
    history_limit: 500,
    history_truncated: false,
  },
};

export const rate: Rate = {
  status: "estimated",
  estimate: { amount: "1900.00", low: "1800.00", high: "2000.00", calculation_mode: "rpm" },
  confidence: { level: "high", data_sufficiency: "sufficient", reasons: ["Exact lane history"] },
  population: { sample_size: 10, selected_tier: "exact", lookback_days: 180, source_types: ["freightflow"] },
};

export const recs: Recs = { recommendations: [], unscored_carriers: [] };

export const sharedRecs: SharedRecs = {
  broker_id: "broker-a",
  load_id: "load-1",
  policy_version: "shared-carrier-pool-v1",
  policy_revision: 1,
  scoring_version: "shared-carrier-recommendations-v1",
  normalization_version: "tx-metro-v1",
  recommendations: [
    {
      scope: "shared",
      rank: 1,
      candidate_id: "shared:opaque-candidate",
      name: "Lone Star Transport",
      match_quality: "exact",
      equipment_type: "dry_van",
      evidence_count_bucket: "3-5",
      contributing_broker_count_bucket: "3-5",
    },
  ],
};

export const sharedRate: SharedRate = {
  scope: "shared",
  broker_id: "broker-a",
  load_id: "load-1",
  policy_version: "shared-carrier-pool-v1",
  policy_revision: 1,
  estimation_version: "shared-carrier-rate-estimation-v1",
  normalization_version: "tx-metro-v1",
  status: "estimated",
  estimate: { amount: "1850.00", low: "1750.00", high: "1950.00", calculation_mode: "median_rate_per_mile" },
  confidence: "medium",
  match_scope: "exact",
  equipment_scope: "equipment",
  sample_count_bucket: "3-5",
  contributing_broker_count_bucket: "3-5",
  selected_tier: "exact_lane_equipment",
  lookback_days: 180,
};

export const candidate: Candidate = {
  candidate_id: "carrier:carrier-1",
  name: "Lone Star Logistics",
  mc_number: "MC-120001",
  dot_number: "DOT-310001",
  carriers: [
    {
      id: "carrier-1",
      name: "Lone Star Logistics",
      mc_number: "MC-120001",
      dot_number: "DOT-310001",
      phone_number: "214-555-1010",
      source_id: "source-a",
      home_city: "Dallas",
      home_state: "TX",
    },
  ],
};
