import type { AttemptTimer } from './types';

// Use elapsed monotonic time, not the phone's wall clock. The server remains authoritative.
export function remainingSeconds(timer: AttemptTimer, elapsedMs: number): number {
  return Math.max(0, Math.ceil(timer.deadline_at - timer.server_now - Math.max(0, elapsedMs) / 1000));
}

export function formatCountdown(seconds: number): string {
  const value = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor(value % 3600 / 60);
  const rest = String(value % 60).padStart(2, '0');
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${rest}` : `${String(minutes).padStart(2, '0')}:${rest}`;
}
