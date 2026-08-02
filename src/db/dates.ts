const pad = (value: number): string => String(value).padStart(2, "0");

export function parseStoredDate(value: string | null | undefined): Date {
  if (!value) return new Date(0);

  const normalized = value.trim().replace(" ", "T");
  const date = new Date(normalized);
  return Number.isNaN(date.valueOf()) ? new Date(0) : date;
}

export function formatLocalDateTime(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

export function formatLocalDate(date: Date): string {
  return formatLocalDateTime(date).slice(0, 10);
}

export function startOfLocalDay(date: Date): Date {
  const result = new Date(date);
  result.setHours(0, 0, 0, 0);
  return result;
}
