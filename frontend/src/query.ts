export type QueueFilters = {
  search: string;
  status: string;
  equipment: string;
  assignment_state: string;
};

export const EMPTY_QUEUE_FILTERS: QueueFilters = {
  search: "",
  status: "",
  equipment: "",
  assignment_state: "",
};

export function parsePage(value: string | null): number {
  const page = Number(value || 1);
  return Number.isInteger(page) && page > 0 ? page : 1;
}

export function parseQueueSearchParams(params: URLSearchParams): {
  filters: QueueFilters;
  page: number;
} {
  return {
    filters: {
      search: params.get("search") || "",
      status: params.get("status") || "",
      equipment: params.get("equipment") || "",
      assignment_state: params.get("assignment_state") || "",
    },
    page: parsePage(params.get("page")),
  };
}

export function buildQueueSearchParams(filters: QueueFilters, page: number): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.search.trim()) params.set("search", filters.search.trim());
  if (filters.status) params.set("status", filters.status);
  if (filters.equipment) params.set("equipment", filters.equipment);
  if (filters.assignment_state) params.set("assignment_state", filters.assignment_state);
  params.set("page", String(Math.max(1, Math.trunc(page))));
  return params;
}
