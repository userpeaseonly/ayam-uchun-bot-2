export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch('/api' + path, {
    credentials: 'same-origin', ...options,
    headers: options.body instanceof FormData ? options.headers : { 'Content-Type': 'application/json', ...options.headers },
  });
  const data = await response.json();
  if (!response.ok) throw new ApiError(data.error || 'So‘rov bajarilmadi.', response.status);
  return data as T;
}

export function post<T>(path: string, data: unknown = {}) {
  return api<T>(path, { method: 'POST', body: JSON.stringify(data) });
}

export function answered(value: string | Record<string, string> | undefined): boolean {
  return typeof value === 'string' ? Boolean(value.trim()) : Boolean(value && Object.values(value).length && Object.values(value).every(v => v.trim()));
}

export function questionAnswered(parts: { id: string }[], value: string | Record<string, string> | undefined): boolean {
  if (!parts.length) return answered(value);
  return typeof value === 'object' && value !== null && parts.every(part => Boolean(value[part.id]?.trim()));
}

export function linkedImport(search: string): string | null {
  const id = new URLSearchParams(search).get('import');
  return id && /^[a-f0-9]{32}$/.test(id) ? id : null;
}
