export function money(value?: string | null): string {
  if (value == null || value.trim() === "") return "—";
  const amount = Number(value);
  if (!Number.isFinite(amount)) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
}

function parseDate(value: string): Date | null {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function date(value?: string | null): string {
  if (!value) return "—";
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(value);
  const parsed = parseDate(dateOnly ? `${value}T00:00:00Z` : value);
  if (!parsed) return "—";
  return new Intl.DateTimeFormat(
    undefined,
    dateOnly
      ? { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }
      : { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" },
  ).format(parsed);
}

export function day(value?: string | null): string {
  if (!value) return "—";
  const parsed = parseDate(`${value.slice(0, 10)}T00:00:00Z`);
  if (!parsed) return "—";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(parsed);
}

export function location(value?: { city: string; state: string } | null): string {
  if (!value?.city && !value?.state) return "—";
  return [value.city, value.state].filter(Boolean).join(", ");
}

export function percentage(margin?: string | null, customerRate?: string | null): string {
  const marginValue = margin == null ? NaN : Number(margin);
  const rateValue = customerRate == null ? NaN : Number(customerRate);
  if (!Number.isFinite(marginValue) || !Number.isFinite(rateValue) || rateValue === 0) {
    return "—";
  }
  return `${((marginValue / rateValue) * 100).toFixed(1)}%`;
}
