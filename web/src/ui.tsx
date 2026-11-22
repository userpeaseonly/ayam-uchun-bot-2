import { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';

export type IconName = 'arrow' | 'back' | 'book' | 'grid' | 'upload' | 'file' | 'image' | 'check' | 'close' | 'chevron' | 'clock' | 'chart' | 'plus' | 'search' | 'help' | 'send' | 'shield' | 'download' | 'refresh' | 'spark' | 'copy' | 'edit' | 'users' | 'logout';
const paths: Record<IconName, ReactNode> = {
  arrow: <path d="M5 12h14m-6-6 6 6-6 6" />,
  back: <path d="M19 12H5m6-6-6 6 6 6" />,
  book: <><path d="M12 5v15M3 4c4-1 7 0 9 2 2-2 5-3 9-2v15c-4-1-7 0-9 2-2-2-5-3-9-2Z" /></>,
  grid: <><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></>,
  upload: <path d="M12 16V3m-5 5 5-5 5 5M4 15v5a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-5" />,
  file: <><path d="M14 3H5v18h14V8Zm0 0v5h5M8 13h8M8 17h5" /></>,
  image: <><rect x="3" y="3" width="18" height="18" rx="3" /><circle cx="8" cy="8" r="1.5" /><path d="m3 17 5-5 4 4 4-6 5 7" /></>,
  check: <path d="m5 12 4 4L19 6" />,
  close: <path d="m6 6 12 12M6 18 18 6" />,
  chevron: <path d="m9 5 7 7-7 7" />,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
  chart: <><path d="M4 3v17h17M8 15v-4m5 4V7m5 8V4" /></>,
  plus: <path d="M12 5v14M5 12h14" />,
  search: <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 5 5" /></>,
  help: <><circle cx="12" cy="12" r="9" /><path d="M9.5 9a2.5 2.5 0 0 1 5 0c0 2-2.5 2-2.5 4m0 3h.01" /></>,
  send: <path d="m21 3-7 18-4-7-7-4Zm0 0L10 14" />,
  shield: <><path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6Z" /><path d="m8 12 3 3 5-6" /></>,
  download: <path d="M12 3v13m-5-5 5 5 5-5M4 16v5h16v-5" />,
  refresh: <><path d="M20 8a8 8 0 1 0 0 8M20 3v5h-5" /></>,
  spark: <><path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5Z" /></>,
  copy: <><rect x="8" y="8" width="12" height="13" rx="2" /><path d="M15 8V3H3v13h5" /></>,
  edit: <path d="m15 4 5 5M4 20l5-1L21 7l-5-5L4 14ZM3 21h18" />,
  users: <><circle cx="9" cy="8" r="3" /><path d="M3 21v-3a6 6 0 0 1 12 0v3m2-16a3 3 0 0 1 0 6m1 4a5 5 0 0 1 3 5v1" /></>,
  logout: <path d="M9 4H4v16h5m4-12 4 4-4 4m-5-4h13" />,
};

export function Icon({ name, size = 20, className = '' }: { name: IconName; size?: number; className?: string }) {
  return <svg className={'icon ' + className} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

export function Brand({ large = false }: { large?: boolean }) {
  return <div className={'brand ' + (large ? 'brand-large' : '')}><img src="/basirat-logo.png" alt="" /><div><span className="brand-name">Basirat<span>.</span></span><span className="brand-caption">TA’LIM MARKAZI</span></div></div>;
}

export function Alert({ children, tone = 'error' }: { children: ReactNode; tone?: 'error' | 'notice' | 'warning' }) {
  return <div className={'alert ' + tone} role={tone === 'error' ? 'alert' : 'status'}><Icon name={tone === 'notice' ? 'check' : 'help'} /><div>{children}</div></div>;
}

export function EmptyState({ icon = 'book', title, children, action }: { icon?: IconName; title: string; children: ReactNode; action?: ReactNode }) {
  return <div className="empty-state"><span className="empty-icon"><Icon name={icon} size={28} /></span><h3>{title}</h3><p>{children}</p>{action}</div>;
}

export function Loading({ label = 'Yuklanmoqda…' }: { label?: string }) {
  return <div className="loading-state" role="status"><span className="spinner" /><span>{label}</span></div>;
}

export function useMediaQuery(query: string) {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const media = window.matchMedia(query);
    const update = () => setMatches(media.matches);
    update(); media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, [query]);
  return matches;
}

const NavigationContext = createContext<{ register(guard: () => Promise<void>): () => void; leave(): Promise<void> }>({ register: () => () => {}, leave: async () => {} });
export function NavigationProvider({ children }: { children: ReactNode }) {
  const guard = useRef<(() => Promise<void>) | null>(null);
  const navigation = useMemo(() => ({
    register(callback: () => Promise<void>) { guard.current = callback; return () => { if (guard.current === callback) guard.current = null; }; },
    async leave() { await guard.current?.(); },
  }), []);
  return <NavigationContext.Provider value={navigation}>{children}</NavigationContext.Provider>;
}
export const useNavigation = () => useContext(NavigationContext);
export function useExitGuard(callback: () => Promise<void>) {
  const navigation = useNavigation();
  const current = useRef(callback); current.current = callback;
  useEffect(() => navigation.register(() => current.current()), [navigation]);
}

export function useTelegramBack(callback: () => void) {
  const current = useRef(callback); current.current = callback;
  useEffect(() => {
    const telegram = window.Telegram?.WebApp;
    const button = telegram?.initData ? telegram.BackButton : undefined;
    if (!button) return;
    const back = () => current.current();
    button.onClick(back); button.show();
    return () => { button.offClick(back); button.hide(); };
  }, []);
}

export function Badge({ status }: { status: string }) {
  return <span className={'badge status-' + status}><span />{statusLabel(status)}</span>;
}

export function statusLabel(status: string) {
  return ({ collecting: 'Rasmlar yig‘ilmoqda', queued: 'Navbatda', processing: 'AI ajratmoqda', failed: 'Qayta urinish kerak', review: 'Tekshirishga tayyor', published: 'Nashr qilingan', active: 'Faol', finished: 'Yakunlangan' } as Record<string, string>)[status] || status;
}

type Confirmation = { title: string; description: string; action?: string; danger?: boolean };
const ConfirmationContext = createContext<(options: Confirmation) => Promise<boolean>>(async () => false);
export const useConfirmation = () => useContext(ConfirmationContext);

export function ConfirmationProvider({ children }: { children: ReactNode }) {
  const [options, setOptions] = useState<Confirmation | null>(null);
  const pending = useRef<((result: boolean) => void) | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { if (options) dialog.current?.showModal(); }, [options]);
  useEffect(() => () => pending.current?.(false), []);
  function settle(value: boolean) { dialog.current?.close(); pending.current?.(value); pending.current = null; setOptions(null); }
  function confirm(value: Confirmation) { pending.current?.(false); setOptions(value); return new Promise<boolean>(resolve => { pending.current = resolve; }); }
  return <ConfirmationContext.Provider value={confirm}>{children}<dialog ref={dialog} className="modal" aria-labelledby="confirmation-title" aria-describedby="confirmation-description" onCancel={event => { event.preventDefault(); settle(false); }}>
    {options && <><span className={'modal-icon ' + (options.danger ? 'destructive' : '')}><Icon name={options.danger ? 'help' : 'shield'} size={26} /></span><h2 id="confirmation-title">{options.title}</h2><p id="confirmation-description">{options.description}</p><div className="actions"><button className="secondary" autoFocus onClick={() => settle(false)}>Bekor qilish</button><button className={options.danger ? 'danger-solid' : ''} onClick={() => settle(true)}>{options.action || 'Tasdiqlash'}<Icon name="arrow" size={18} /></button></div></>}
  </dialog></ConfirmationContext.Provider>;
}

export function Guide({ open, close }: { open: boolean; close(): void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { if (open) dialog.current?.showModal(); else dialog.current?.close(); }, [open]);
  return <dialog ref={dialog} className="modal guide-modal" aria-labelledby="guide-title" onCancel={event => { event.preventDefault(); close(); }}><div className="section-heading"><span className="eyebrow">BASIRAT YORDAM</span><button className="icon-button" aria-label="Yordamni yopish" onClick={close}><Icon name="close" /></button></div><h2 id="guide-title">Hammasi oddiy.</h2><ol className="guide-steps"><li><span>01</span><div><h3>Test kodini kiriting</h3><p>Kodni o‘qituvchingizdan oling yoki u yuborgan havolani oching.</p></div></li><li><span>02</span><div><h3>Savollarga javob bering</h3><p>Javoblar avtomatik saqlanadi. Topshirishdan oldin ularni tekshirib chiqing.</p></div></li><li><span>03</span><div><h3>Natijangizni kuzating</h3><p>To‘g‘ri va noto‘g‘ri javoblar ko‘rinadi. Ochiq javoblar tekshirilishi kutilishi mumkin. Ball va o‘rin test yakunlangach ochiladi.</p></div></li></ol><div className="help-note"><Icon name="upload" /><p>O‘qituvchimisiz? O‘qituvchi bo‘limida PDF yoki rasmlarni yuklang, AI ajratgan savollarni tekshirib, testni nashr qiling.</p></div><button className="full-width" onClick={close}>Tushunarli<Icon name="check" size={18} /></button></dialog>;
}
