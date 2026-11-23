import { describe, expect, it } from 'vitest';
import { formatCountdown, remainingSeconds } from './timer';

const timer = { started_at: 1000, deadline_at: 1060, server_now: 1010 };
describe('server-based assessment countdown', () => {
  it('uses elapsed time so changing the phone clock cannot extend a test', () => {
    expect(remainingSeconds(timer, 0)).toBe(50);
    expect(remainingSeconds(timer, 15500)).toBe(35);
    expect(remainingSeconds(timer, 50000)).toBe(0);
    expect(remainingSeconds(timer, 100000)).toBe(0);
  });
  it('resynchronizes to the server after backgrounding or reconnecting', () => {
    expect(remainingSeconds({ ...timer, server_now: 1059.5 }, 499)).toBe(1);
    expect(remainingSeconds({ ...timer, server_now: 1061 }, 0)).toBe(0);
  });
  it('formats minutes and long test durations without wrapping at one hour', () => {
    expect(formatCountdown(0)).toBe('00:00');
    expect(formatCountdown(59)).toBe('00:59');
    expect(formatCountdown(3600)).toBe('1:00:00');
    expect(formatCountdown(86400)).toBe('24:00:00');
  });
});
