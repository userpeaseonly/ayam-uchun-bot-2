import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MAX_VOICE_BYTES, VoiceCapture } from './voice-capture';

class Recorder {
  static instances: Recorder[] = [];
  static isTypeSupported = (type: string) => type === 'audio/mp4';
  state: RecordingState = 'inactive';
  mimeType: string;
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onerror: (() => void) | null = null;
  onstop: (() => void) | null = null;
  constructor(_stream: MediaStream, options: MediaRecorderOptions) {
    this.mimeType = options.mimeType || '';
    Recorder.instances.push(this);
  }
  start() { this.state = 'recording'; }
  stop() {
    this.state = 'inactive';
    this.ondataavailable?.({ data: new Blob(['sample'], { type: this.mimeType }) });
    this.onstop?.();
  }
}

describe('voice capture microphone lifecycle', () => {
  const stop = vi.fn();
  const stream = { getTracks: () => [{ stop }] } as unknown as MediaStream;
  const getUserMedia = vi.fn();
  const ready = vi.fn();
  const error = vi.fn();
  const tick = vi.fn();
  beforeEach(() => {
    vi.useFakeTimers(); vi.clearAllMocks(); Recorder.instances = [];
    getUserMedia.mockResolvedValue(stream);
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia } });
    vi.stubGlobal('MediaRecorder', Recorder);
  });
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });
  const capture = () => new VoiceCapture({ ready, error, tick });

  it('chooses a supported format, emits the recording and releases the microphone', async () => {
    const voice = capture();
    expect(await voice.start()).toBe(true);
    expect(getUserMedia).toHaveBeenCalledWith({ audio: true, video: false });
    expect(Recorder.instances[0].mimeType).toBe('audio/mp4');
    voice.stop();
    expect(ready).toHaveBeenCalledOnce();
    expect(ready.mock.calls[0][0].size).toBeGreaterThan(0);
    expect(stop).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('cancels a late permission grant after leaving or cancelling', async () => {
    let grant!: (value: MediaStream) => void;
    getUserMedia.mockReturnValue(new Promise<MediaStream>(resolve => { grant = resolve; }));
    const voice = capture();
    const starting = voice.start();
    voice.dispose(); grant(stream);
    expect(await starting).toBe(false);
    expect(stop).toHaveBeenCalledOnce();
    expect(Recorder.instances).toHaveLength(0);
    expect(ready).not.toHaveBeenCalled();
  });

  it('stops at two minutes without leaving a microphone or timer running', async () => {
    const voice = capture(); await voice.start();
    vi.advanceTimersByTime(120000);
    expect(ready).toHaveBeenCalledOnce();
    expect(tick).toHaveBeenLastCalledWith(120);
    expect(stop).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('rejects oversize recordings and discards partial audio', async () => {
    const voice = capture(); await voice.start();
    Recorder.instances[0].ondataavailable?.({ data: new Blob([new Uint8Array(MAX_VOICE_BYTES + 1)]) });
    expect(error).toHaveBeenCalledOnce();
    expect(ready).not.toHaveBeenCalled();
    expect(stop).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('releases tracks on recorder failure and does not upload on unmount', async () => {
    const voice = capture(); await voice.start();
    Recorder.instances[0].onerror?.();
    expect(stop).toHaveBeenCalledOnce();
    expect(error).toHaveBeenCalledOnce();
    expect(ready).not.toHaveBeenCalled();
    const another = capture(); await another.start(); another.dispose();
    expect(stop).toHaveBeenCalledTimes(2);
    expect(ready).not.toHaveBeenCalled();
  });

  it('reports denied permission without creating a recorder', async () => {
    getUserMedia.mockRejectedValue(new Error('Permission denied'));
    await expect(capture().start()).rejects.toThrow('Permission denied');
    expect(Recorder.instances).toHaveLength(0);
    expect(ready).not.toHaveBeenCalled();
  });
});
