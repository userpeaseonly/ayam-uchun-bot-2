export const MAX_VOICE_SECONDS = 120;
export const MAX_VOICE_BYTES = 8 * 1024 * 1024;

/** Own the microphone and timers; disposing also cancels late permission grants. */
export class VoiceCapture {
  private recorder: MediaRecorder | null = null;
  private stream: MediaStream | null = null;
  private timer: ReturnType<typeof setInterval> | undefined;
  private chunks: Blob[] = [];
  private size = 0;
  private disposed = false;
  constructor(private callbacks: { ready(blob: Blob): void; error(message: string): void; tick(seconds: number): void }) {}

  async start() {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      throw new Error('Bu oynada ovoz yozish mavjud emas. Telegramni yangilang yoki audio fayl yuklang.');
    }
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    if (this.disposed) { stream.getTracks().forEach(track => track.stop()); return false; }
    this.stream = stream;
    try {
      const mimeType = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/ogg;codecs=opus']
        .find(type => MediaRecorder.isTypeSupported(type));
      const recorder = new MediaRecorder(stream, { audioBitsPerSecond: 64000, ...(mimeType ? { mimeType } : {}) });
      this.recorder = recorder;
      recorder.ondataavailable = event => {
        if (this.disposed || !event.data.size) return;
        this.size += event.data.size;
        if (this.size > MAX_VOICE_BYTES) { this.fail('Yozuv 8 MB dan oshdi. Qisqaroq izoh yozing.'); return; }
        this.chunks.push(event.data);
      };
      recorder.onerror = () => this.fail('Ovoz yozilmadi. Mikrofonni tekshirib, qayta urinib ko‘ring.');
      recorder.onstop = () => {
        const blob = new Blob(this.chunks, { type: recorder.mimeType || this.chunks[0]?.type || 'application/octet-stream' });
        this.release();
        if (this.disposed) return;
        if (blob.size) this.callbacks.ready(blob);
        else this.callbacks.error('Yozuv bo‘sh. Qayta yozib ko‘ring.');
      };
      recorder.start(1000);
      const started = performance.now();
      this.timer = setInterval(() => {
        const seconds = Math.min(MAX_VOICE_SECONDS, Math.floor((performance.now() - started) / 1000));
        this.callbacks.tick(seconds);
        if (seconds >= MAX_VOICE_SECONDS) this.stop();
      }, 250);
      return true;
    } catch (error) { this.release(); throw error; }
  }
  stop() {
    if (this.recorder?.state === 'recording' || this.recorder?.state === 'paused') this.recorder.stop();
  }
  private release() {
    clearInterval(this.timer);
    this.stream?.getTracks().forEach(track => track.stop());
    this.stream = null;
  }
  private fail(message: string) {
    this.dispose(); this.callbacks.error(message);
  }
  dispose() {
    this.disposed = true;
    if (this.recorder) {
      this.recorder.onstop = null; this.recorder.ondataavailable = null; this.recorder.onerror = null;
      this.stop();
    }
    this.release(); this.chunks = [];
  }
}
