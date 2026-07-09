// Display helpers. Decimal strings from the API are parsed ONLY for display — arithmetic on
// money stays server-side.

const usd = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
});

export function money(value: string | null | undefined): string {
  if (value == null) return "—";
  const n = Number(value);
  return Number.isFinite(n) ? usd.format(n) : value;
}

export function qty(value: string): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return value;
  return n % 1 === 0 ? n.toFixed(0) : String(n);
}

export function pct(value: number | string, signed = false): string {
  const n = typeof value === "string" ? Number(value) : value;
  if (!Number.isFinite(n)) return String(value);
  const sign = signed && n > 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}%`;
}
