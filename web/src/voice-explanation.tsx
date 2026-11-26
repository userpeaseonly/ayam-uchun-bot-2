import { useEffect, useRef, useState } from 'react';
import { api } from './api';
import { Alert, Icon } from './ui';
import { AudioPlayer } from './audio-player';
import { MAX_VOICE_BYTES, VoiceCapture } from './voice-capture';
import './voice-explanation.css';

type Props = { importId: string; number: number; audio?: string; saved(id: string): void; activity(busy: boolean): void };
export function VoiceExplanation({ importId, number, audio, saved, activity }: Props) {
  const [phase, setPhase] = useState<'idle' | 'permission' | 'recording' | 'uploading' | 'retry'>('idle');
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState('');
  const [preview, setPreview] = useState('');
  const capture = useRef<VoiceCapture | null>(null);
  const pending = useRef<Blob | null>(null);
  const localUrl = useRef('');
  const alive = useRef(true);
  const callbacks = useRef({ saved, activity }); callbacks.current = { saved, activity };
  const request = useRef<AbortController | null>(null);
  function clearPreview() {
    if (localUrl.current) URL.revokeObjectURL(localUrl.current);
    localUrl.current = ''; setPreview(''); pending.current = null;
  }
  async function upload(blob: Blob) {
    pending.current = blob;
    setPhase('uploading'); setError(''); callbacks.current.activity(true);
    const controller = new AbortController(); request.current = controller;
    try {
      const result = await api<{ id: string }>('/teacher/imports/' + importId + '/explanations', {
        method: 'POST', body: blob, signal: controller.signal,
        headers: { 'Content-Type': blob.type || 'application/octet-stream' },
      });
      if (!alive.current || controller.signal.aborted) return;
      capture.current?.dispose(); capture.current = null;
      callbacks.current.saved(result.id); clearPreview(); setPhase('idle'); callbacks.current.activity(false);
    } catch (error) {
      if (!alive.current || controller.signal.aborted) return;
      setPhase('retry'); setError(error instanceof Error ? error.message : 'Yozuv yuklanmadi. Qayta urinib ko‘ring.');
    }
  }
  function ready(blob: Blob) {
    if (!alive.current) return;
    capture.current?.dispose(); capture.current = null;
   
    if (blob.size > MAX_VOICE_BYTES) { setError('Audio 8 MB dan oshmasligi kerak.'); setPhase('idle'); callbacks.current.activity(false); return; }
    if (localUrl.current) URL.revokeObjectURL(localUrl.current);
    localUrl.current = URL.createObjectURL(blob); setPreview(localUrl.current); void upload(blob);
  }
  async function start() {
    setError(''); setSeconds(0); setPhase('permission'); callbacks.current.activity(true);
    const recorder = new VoiceCapture({ ready, tick: setSeconds, error(message) {
      if (!alive.current) return;
      capture.current = null;
      setError(message); setPhase('idle'); callbacks.current.activity(false);
    } });
    capture.current = recorder;
    try { if (await recorder.start() && alive.current && capture.current === recorder) setPhase('recording'); }
    catch (error) {
      if (!alive.current || capture.current !== recorder) return;
      recorder.dispose(); capture.current = null; setPhase('idle'); callbacks.current.activity(false);
      setError(error instanceof Error && error.name !== 'NotAllowedError' ? error.message : 'Mikrofonga ruxsat bering. Ruxsat bo‘lmasa audio fayl yuklashingiz mumkin.');
    }
  }
  function discard() {
    request.current?.abort(); request.current = null;
    capture.current?.dispose(); capture.current = null; clearPreview(); setPhase('idle'); setError(''); callbacks.current.activity(false);
  }
  useEffect(() => {
    alive.current = true;
    const hidden = () => { if (document.visibilityState === 'hidden') capture.current?.stop(); };
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (capture.current || pending.current) { event.preventDefault(); event.returnValue = ''; }
    };
    document.addEventListener('visibilitychange', hidden); window.addEventListener('beforeunload', beforeUnload);
    return () => {
      alive.current = false; capture.current?.dispose(); request.current?.abort();
      if (localUrl.current) URL.revokeObjectURL(localUrl.current);
      callbacks.current.activity(false);
      document.removeEventListener('visibilitychange', hidden); window.removeEventListener('beforeunload', beforeUnload);
    };
  }, []);
  const busy = phase !== 'idle';
  return <section className="voice-explanation" aria-label={`${number}-savol ovozli izohi`}>
    <div className="voice-heading"><Icon name="mic" size={19} /><strong>Ovozli izoh</strong><span>Ixtiyoriy</span></div>
    <p>O‘quvchi testni topshirgach tinglaydi. Eng ko‘pi 2 daqiqa.</p>
    {(preview || audio) && <AudioPlayer key={preview || audio} src={preview || '/api/assets/' + audio} label={`${number}-savol izohi`} />}
    <div className="actions voice-actions">
      {phase === 'recording' ? <><span className="recording-clock" role="timer" aria-label="Yozuv davomiyligi"><i />{Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, '0')}</span><button className="secondary" onClick={() => capture.current?.stop()}><Icon name="stop" size={17} />To‘xtatish</button><button className="quiet" onClick={discard}>Bekor qilish</button></> : phase === 'permission' ? <><span role="status">Mikrofon ruxsati kutilmoqda…</span><button className="quiet" onClick={discard}>Bekor qilish</button></> : phase === 'uploading' ? <><span role="status"><span className="spinner" />Yozuv yuklanmoqda…</span><button className="quiet" onClick={discard}>Bekor qilish</button></> : phase === 'retry' ? <><button className="secondary" onClick={() => pending.current && void upload(pending.current)}>Qayta yuklash</button><button className="quiet" onClick={discard}>Yozuvni bekor qilish</button></> : <>
        <button className="secondary" onClick={() => void start()}><Icon name="mic" size={17} />{audio ? 'Qayta yozish' : 'Ovoz yozish'}</button>
        {audio && <button className="quiet" onClick={() => { saved(''); }}>Izohni olib tashlash</button>}
      </>}
    </div>
    {!busy && <label className="voice-upload">Audio fayl yuklash<input type="file" accept="audio/*,.webm,.mp4,.ogg" aria-label={`${number}-savol uchun audio yuklash`} onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) { setError(''); ready(file); } }} /></label>}
    {error && <Alert>{error}</Alert>}
  </section>;
}

export function ExplanationPlayer({ url, number }: { url: string; number: number }) {
  return <div className="submitted-explanation"><AudioPlayer src={url} label={`${number}-savol izohi`} /></div>;
}
