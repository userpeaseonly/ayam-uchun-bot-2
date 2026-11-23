import { useEffect, useRef, useState } from 'react';
import { api } from './api';
import type { AttemptTimer, StudentTest, Submission } from './types';
import { remainingSeconds } from './timer';

type Status = { timer: AttemptTimer | null; submission: Submission | null };
export function useAttemptTimer(initial: Pick<StudentTest, 'public_id' | 'timer'>, result: Submission | null, submitted: (value: Submission) => void) {
  const onSubmitted = useRef(submitted); onSubmitted.current = submitted;
  const anchor = useRef({ timer: initial.timer, receivedAt: performance.now() });
  const [seconds, setSeconds] = useState<number | null>(initial.timer ? remainingSeconds(initial.timer, 0) : null);
  const [problem, setProblem] = useState('');
  const request = useRef<Promise<Status | null> | null>(null);
  const lastSync = useRef(performance.now());
  const latestResult = useRef(result); latestResult.current = result;
  function remaining() {
    return anchor.current.timer ? remainingSeconds(anchor.current.timer, performance.now() - anchor.current.receivedAt) : null;
  }
  async function sync(): Promise<Status | null> {
    if (!anchor.current.timer) return null;
    if (request.current) return request.current;
    lastSync.current = performance.now();
    const task = (async () => {
      try {
        const value = await api<Status>('/tests/' + initial.public_id + '/timer');
        anchor.current = { timer: value.timer, receivedAt: performance.now() };
        setSeconds(remaining()); setProblem('');
        if (value.submission) onSubmitted.current(value.submission);
        return value;
      } catch (error) {
        setProblem('Server bilan bog‘lanib bo‘lmadi. Ulanish tiklangach natija yangilanadi; vaqt davom etmoqda.');
        throw error;
      }
    })();
    request.current = task;
    try { return await task; } finally { request.current = null; }
  }
  useEffect(() => {
    if (!initial.timer || result) return;
    const resync = () => { if (!latestResult.current) void sync().catch(() => {}); };
    const visible = () => { if (document.visibilityState === 'visible') resync(); };
    const tick = setInterval(() => {
      const value = remaining(); setSeconds(value);
      if (!latestResult.current && performance.now() - lastSync.current >= (value === 0 ? 3000 : 15000)) resync();
    }, 1000);
    window.addEventListener('focus', resync); window.addEventListener('online', resync);
    document.addEventListener('visibilitychange', visible);
    return () => { clearInterval(tick); window.removeEventListener('focus', resync); window.removeEventListener('online', resync); document.removeEventListener('visibilitychange', visible); };
  }, [Boolean(result)]);
  return { seconds, expired: seconds === 0, isExpired: () => remaining() === 0, sync, problem };
}
