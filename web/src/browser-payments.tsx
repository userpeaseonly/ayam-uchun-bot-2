import { useEffect, useRef, useState } from 'react';
import { api, post } from './api';
import { Alert, Icon, Loading, PageControls, usePagedList } from './ui';
import './payments.css';

type Provider = 'click' | 'payme';
type Order = { id: string; provider: Provider; environment: string; status: string; amount_uzs: number; created_at: number; checkout_url?: string };
type History = { settings: { providers: { id: Provider; enabled: boolean; environment: string }[]; terms_version: string; terms_text: string; support_url: string | null }; orders: Order[] };
const errorText = (error: unknown) => error instanceof Error ? error.message : 'So‘rov bajarilmadi.';
const labels: Record<string, string> = { created: 'To‘lov kutilmoqda', pending: 'Provayder tasdig‘i kutilmoqda', paid: 'To‘langan', cancelled: 'Bekor qilingan', refunded: 'Qaytarilgan', expired: 'Muddati tugagan' };
const name = (provider: Provider) => provider === 'click' ? 'Click' : 'Payme';

export function BrowserLogin<T>({ completed }: { completed(identity: T): void }) {
  const [challenge, setChallenge] = useState<{ code: string; bot_url: string } | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const attempt = useRef(0);
  async function start() {
    ++attempt.current; setChallenge(null); setBusy(true); setError('');
    try { setChallenge(await post('/browser-login')); } catch (error) { setError(errorText(error)); } finally { setBusy(false); }
  }
  useEffect(() => {
    if (!challenge) return;
    let active = true; let timer: ReturnType<typeof setTimeout>;
    const current = attempt.current;
    async function check() {
      try {
        const result = await api<{ pending: boolean; identity?: T }>('/browser-login');
        if (!active || current !== attempt.current) return;
        if (!result.pending && result.identity) { completed(result.identity); return; }
        timer = setTimeout(() => void check(), 2000);
      } catch (error) { if (active && current === attempt.current) setError(errorText(error)); }
    }
    void check();
    return () => { active = false; clearTimeout(timer); };
  }, [challenge]);
  return <><span className="empty-icon"><Icon name="send" size={26} /></span><h1>Hisobga kirish</h1><p>Telegramda tasdiqlang, so‘ng shu oynaga qayting.</p>
    {error && <Alert>{error}</Alert>}
    {challenge && <div className="browser-login-code"><span>Tasdiqlash kodi</span><strong>{challenge.code}</strong><p>Botdagi kod shu kod bilan bir xil bo‘lishi kerak.</p><a className="button" href={challenge.bot_url} target="_blank" rel="noreferrer">Telegramda tasdiqlash<Icon name="send" size={17} /></a><p className="muted">Tasdiq kutilmoqda…</p></div>}
    <button disabled={busy} className={challenge ? 'secondary' : ''} onClick={() => void start()}>{busy ? 'Kutilmoqda…' : challenge ? 'Kirishni qayta boshlash' : 'Telegram orqali kirish'}</button>
  </>;
}

export function BrowserPaymentPanel() {
  const [history, setHistory] = useState<History | null>(null);
  const [accepted, setAccepted] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const keys = useRef({ click: crypto.randomUUID().replaceAll('-', ''), payme: crypto.randomUUID().replaceAll('-', '') });
  const orderPage = usePagedList(history?.orders || [], 3, 0);
  const termsVersion = useRef('');
  const generation = useRef(0);
  const alive = useRef(true);
  async function refresh() {
    const current = ++generation.current;
    try {
      const result = await api<History>('/web-payments');
      if (!alive.current || current !== generation.current) return;
      if (termsVersion.current && termsVersion.current !== result.settings.terms_version) setAccepted(false);
      termsVersion.current = result.settings.terms_version;
      setHistory(result); setError('');
    } catch (error) { if (alive.current && current === generation.current) setError(errorText(error)); }
  }
  useEffect(() => {
    alive.current = true; void refresh();
    const update = () => { if (document.visibilityState === 'visible') void refresh(); };
    const timer = setInterval(update, 5000);
    window.addEventListener('focus', update); window.addEventListener('online', update); document.addEventListener('visibilitychange', update);
    return () => { alive.current = false; ++generation.current; clearInterval(timer); window.removeEventListener('focus', update); window.removeEventListener('online', update); document.removeEventListener('visibilitychange', update); };
  }, []);
  async function create(provider: Provider) {
    if (!accepted || !history || busy) return;
    setBusy(true); setError('');
    try {
      const order = await post<Order>('/web-payments/test', { provider, request_key: keys.current[provider], terms_version: history.settings.terms_version, accepted_terms: true });
      keys.current[provider] = crypto.randomUUID().replaceAll('-', '');
      if (order.checkout_url) window.location.assign(order.checkout_url); else await refresh();
    } catch (error) { setError(errorText(error)); } finally { setBusy(false); }
  }
  if (window.Telegram?.WebApp.initData) return null;
  return <section className="card payment-panel" aria-label="Click va Payme sinov to‘lovlari"><span className="eyebrow">ADMIN UCHUN SINOV · BRAUZER</span><h2>Click va Payme</h2><p>1 000 so‘mlik integratsiya sinovi. Test yoki balans ochilmaydi.</p>
    {error && <Alert>{error}<button className="quiet" onClick={() => void refresh()}>Holatni yangilash</button></Alert>}
    {!history ? !error && <Loading label="To‘lovlar yuklanmoqda…" /> : <>
      <details className="payment-terms"><summary>Sinov shartlari<Icon name="file" size={17} /></summary><p>{history.settings.terms_text}</p><small>Versiya: {history.settings.terms_version}</small></details>
      <label className="payment-consent"><input type="checkbox" checked={accepted} disabled={busy} onChange={event => setAccepted(event.target.checked)} /><span>Sinov shartlarini o‘qidim va roziman.</span></label>
      <div className="web-payment-options">{history.settings.providers.map(provider => <div key={provider.id}><strong>{name(provider.id)}</strong><p>{provider.enabled ? provider.environment === 'test' ? provider.id === 'click' ? 'Alohida Click test xizmati' : 'Payme sandbox · haqiqiy pul sarflanmaydi' : 'Jonli muhit · haqiqiy pul sarflanadi' : 'Hali sozlanmagan yoki o‘chirilgan'}</p><button disabled={busy || !accepted || !provider.enabled} onClick={() => void create(provider.id)}>1 000 so‘m · {name(provider.id)}</button></div>)}</div>
      <p className="muted">To‘lovdan keyin shu saytga qayting. Holat server tasdig‘i bilan yangilanadi.</p>
      <div className="payment-history-heading"><h3>To‘lovlar tarixi</h3><button className="icon-button" aria-label="Brauzer to‘lov tarixini yangilash" onClick={() => void refresh()}><Icon name="refresh" size={18} /></button></div>
      {!history.orders.length ? <p>Hali to‘lovlar yo‘q.</p> : <ol className="payment-history">{orderPage.items.map(order => <li key={order.id}><div className="payment-row-heading"><strong>{order.amount_uzs.toLocaleString('uz-UZ')} so‘m · {name(order.provider)}</strong><span className={'payment-status payment-' + order.status}>{labels[order.status] || order.status}</span></div><details className="payment-receipt"><summary>Buyurtma raqami</summary><p className="payment-reference">{order.id}</p></details><small>{order.environment === 'test' ? 'Test muhiti' : 'Jonli muhit'} · {new Date(order.created_at).toLocaleString('uz-UZ')}</small>{order.checkout_url && <div className="actions"><a href={order.checkout_url} className="button secondary">To‘lovni davom ettirish</a></div>}</li>)}</ol>}
      <PageControls page={orderPage.page} pages={orderPage.pages} onChange={orderPage.setPage} label="Brauzer to‘lovlari sahifalari" />
      {history.settings.support_url && <a className="payment-support" href={history.settings.support_url} target="_blank" rel="noreferrer">To‘lov bo‘yicha yordam va qaytarish<Icon name="help" size={17} /></a>}
    </>}
  </section>;
}
