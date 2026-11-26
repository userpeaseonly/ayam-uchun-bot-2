import { useEffect, useId, useRef, useState } from 'react';
import { Icon } from './ui';

const stamp = (value: number) => `${Math.floor(value / 60)}:${String(Math.floor(value % 60)).padStart(2, '0')}`;

/** Deliberately has no native menu, download link or remote-playback control.
 * This discourages saving; media delivered to a browser is not DRM protected. */
export function AudioPlayer({ src, label }: { src: string; label: string }) {
  const source = useRef<HTMLAudioElement>(null);
  const identity = useId();
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(false);
  const [duration, setDuration] = useState(0);
  const [position, setPosition] = useState(0);
  const [error, setError] = useState('');
  useEffect(() => {
    const otherPlayer = (event: Event) => {
      if ((event as CustomEvent<string>).detail !== identity) source.current?.pause();
    };
    document.addEventListener('basirat-audio-play', otherPlayer);
    const element = source.current;
    element?.setAttribute('disableremoteplayback', '');
    return () => { document.removeEventListener('basirat-audio-play', otherPlayer); element?.pause(); };
  }, [identity]);
  async function toggle() {
    const audio = source.current;
    if (!audio) return;
    setError('');
    if (!audio.paused) { audio.pause(); return; }
    setLoading(true);
    try { await audio.play(); }
    catch (error) {
      setLoading(false);
      if (!(error instanceof DOMException && error.name === 'AbortError')) setError('Ovoz ochilmadi. Internetni tekshirib, qayta urinib ko‘ring.');
    }
  }
  return <div className="audio-player" role="group" aria-label={label} onContextMenu={event => event.preventDefault()}>
    <audio ref={source} className="audio-player-source" hidden preload="none" src={src}
      controlsList="nodownload noremoteplayback"
      onPlay={() => { setPlaying(true); document.dispatchEvent(new CustomEvent('basirat-audio-play', { detail: identity })); }}
      onPlaying={() => setLoading(false)} onWaiting={() => setLoading(true)}
      onPause={() => { setPlaying(false); setLoading(false); }} onEnded={() => { setPlaying(false); setLoading(false); }}
      onLoadedMetadata={event => setDuration(Number.isFinite(event.currentTarget.duration) ? event.currentTarget.duration : 0)}
      onTimeUpdate={event => setPosition(event.currentTarget.currentTime)}
      onError={() => { setLoading(false); setPlaying(false); setError('Ovoz ochilmadi. Internetni tekshirib, qayta urinib ko‘ring.'); }} />
    <button className="audio-play" type="button" onClick={() => void toggle()} aria-label={(playing ? 'To‘xtatib turish: ' : 'Tinglash: ') + label}>
      {loading ? <span className="spinner" /> : <Icon name={playing ? 'pause' : 'play'} size={19} />}
    </button>
    <div className="audio-track"><input type="range" min={0} max={duration || 1} step={0.1} value={Math.min(position, duration || 1)} disabled={!duration}
      aria-label={label + ' · vaqt'} aria-valuetext={`${stamp(position)} / ${duration ? stamp(duration) : '—'}`}
      onChange={event => { if (source.current) { source.current.currentTime = Number(event.target.value); setPosition(Number(event.target.value)); } }} />
      <span>{stamp(position)} <span>/ {duration ? stamp(duration) : '—'}</span></span>
    </div>
    {error && <p className="audio-error" role="status">{error}</p>}
  </div>;
}
