export function money(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  const number = Number(value);
  const digits = number >= 1000 ? 0 : number >= 1 ? 2 : 5;
  return new Intl.NumberFormat("es-CL", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: digits,
  }).format(number);
}

export function compact(value) {
  if (value == null) return "—";
  return new Intl.NumberFormat("es-CL", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

export function dateTime(value) {
  if (!value) return "Sin datos";
  return new Intl.DateTimeFormat("es-CL", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

