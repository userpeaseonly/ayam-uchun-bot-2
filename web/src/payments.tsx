import { useEffect, useRef, useState } from 'react';
import { api, post } from './api';
import { Alert, Icon, Loading, PageControls, usePagedList, useConfirmation } from './ui';
import type { PaymentHistory, PaymentOrder, InvoiceStatus } from './types';
import './payments.css';

const labels: Record<PaymentOrder['status'], string> = {
  created: 'Hisob tayyorlanmoqda', invoice_ready: 'To‘lov kutilmoqda', invoice_failed: 'Hisob yaratilmagan',
  checkout: 'Telegram tasdig‘i kutilmoqda', paid: 'To‘langan', refund_pending: 'Qaytarilmoqda', refunded: 'Qaytarilgan', expired: 'Muddati tugagan',
};
const problem = (error: unknown) => error instanceof Error ? error.message : 'To‘lov holatini yuklab bo‘lmadi.';

export function PaymentPanel() {
  const [history, setHistory] = useState<PaymentHistory | null>(null);
  const [accepted, setAccepted] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const generation = useRef(0);
  const alive = useRef(true);
  const requestKey = useRef(crypto.randomUUID().replaceAll('-', ''));
  const termsVersion = useRef('');
  const confirm = useConfirmation();
  const telegram = window.Telegram?.WebApp;
  const orderPage = usePagedList(history?.orders || [], 3, 0);
  const nativeCheckout = Boolean(telegram?.initData && telegram?.openInvoice);
  async function refresh() {
    const current = ++generation.current;
    try {
      const result = await api<PaymentHistory>('/payments');
      if (!alive.current || current !== generation.current) return;
      if (termsVersion.current && termsVersion.current !== result.settings.terms_version) setAccepted(false);
      termsVersion.current = result.settings.terms_version;
      setHistory(result);
      setError('');
    } catch (error) { if (alive.current && current === generation.current) setError(problem(error)); }
  }
  useEffect(() => {
    alive.current = true; void refresh();
    const tick = setInterval(() => { if (document.visibilityState === 'visible') void refresh(); }, 5000);
    const visible = () => { if (document.visibilityState === 'visible') void refresh(); };
    window.addEventListener('focus', visible); window.addEventListener('online', visible); document.addEventListener('visibilitychange', visible);
    return () => { alive.current = false; ++generation.current; clearInterval(tick); window.removeEventListener('focus', visible); window.removeEventListener('online', visible); document.removeEventListener('visibilitychange', visible); };
  }, []);
  function open(order: PaymentOrder) {
    if (!nativeCheckout || !order.invoice_url) { setError('Hisobni Telegram ichida oching.'); return; }
    setNotice('Hisob Telegramda ochildi. To‘lov holati serverdan tasdiqlanadi.');
    try {
      telegram!.openInvoice!(order.invoice_url, (status: InvoiceStatus) => {
        if (!alive.current) return;
        setNotice(status === 'cancelled' ? 'To‘lov oynasi yopildi. Serverdagi holat tarixda ko‘rsatiladi.' : status === 'failed' ? 'Telegram to‘lovni yakunlay olmadi. Tarixni tekshirib, qayta urinishingiz mumkin.' : 'Telegram tasdig‘i tekshirilmoqda. Holat avtomatik yangilanadi.');
        void refresh();
      });
    } catch { setError('Telegram hisobini ochib bo‘lmadi. Ilovani yangilang va tarixdagi hisobni qayta oching.'); }
  }
  async function create() {
    if (!history || !accepted || busy || !nativeCheckout) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const order = await post<PaymentOrder>('/payments/stars/test', { request_key: requestKey.current, accepted_terms: true, terms_version: history.settings.terms_version });
      // Keep the same key after transport errors; a retry must recover the order.
      requestKey.current = crypto.randomUUID().replaceAll('-', '');
      await refresh(); open(order);
    } catch (error) { setError(problem(error)); }
    finally { setBusy(false); }
  }
  async function refund(order: PaymentOrder) {
    if (!await confirm({ title: 'Stars qaytarilsinmi?', description: `${order.amount} Stars shu to‘lovni qilgan Telegram hisobiga to‘liq qaytariladi.`, action: 'Starsni qaytarish' })) return;
    setBusy(true); setError(''); setNotice('');
    try { await post('/payments/orders/' + order.id + '/refund'); setNotice('Qaytarish so‘rovi saqlandi. Telegram tasdiqlagach holat yangilanadi.'); await refresh(); }
    catch (error) { setError(problem(error)); } finally { setBusy(false); }
  }
  return <section className="card payment-panel" aria-label="Stars sinov to‘lovlari"><div className="section-heading"><div><span className="eyebrow">ADMIN UCHUN SINOV</span><h2>Telegram Stars</h2></div><Icon name="spark" size={25} /></div>
    {error && <Alert>{error}<button className="quiet" onClick={() => void refresh()}>Holatni yangilash</button></Alert>}
    {!history ? !error && <Loading label="To‘lov tarixi yuklanmoqda…" /> : <>
      <p>Integratsiya sinovi. Test yoki balans ochilmaydi.</p>
      <span className={'payment-environment ' + (history.settings.environment === 'live' ? 'live' : '')}>{history.settings.environment === 'test' ? 'Telegram test serveri · haqiqiy Stars sarflanmaydi' : 'Jonli muhit · haqiqiy Stars sarflanadi'}</span>
      {history.settings.enabled ? <>
        <details className="payment-terms"><summary>Sinov shartlari<Icon name="file" size={17} /></summary><p>{history.settings.terms_text}</p><small>Versiya: {history.settings.terms_version}</small></details>
        <label className="payment-consent"><input type="checkbox" checked={accepted} disabled={busy} onChange={event => setAccepted(event.target.checked)} /><span>Sinov shartlarini o‘qidim va roziman. {history.settings.environment === 'live' ? 'Haqiqiy 1 Stars sarflanishini tushunaman.' : 'Bu Telegram test serveridagi sinov ekanini tushunaman.'}</span></label>
        {!nativeCheckout && <Alert tone="notice">Hisobni to‘lash uchun Mini App’ni Telegram ichida oching. Bu sahifada to‘lov tarixini ko‘rishingiz mumkin.</Alert>}
        <button disabled={busy || !accepted || !nativeCheckout} onClick={() => void create()}><Icon name="spark" size={18} />{busy ? 'Kutilmoqda…' : 'Sinov to‘lovi · ⭐ 1'}</button>
      </> : <p className="muted">Yangi sinov to‘lovlari o‘chirilgan. Avvalgi to‘lovlar va qaytarish imkoniyati saqlanadi.</p>}
      {notice && <p className="payment-notice" role="status">{notice}</p>}
      <div className="payment-history-heading"><h3>To‘lovlar tarixi</h3><button className="icon-button" disabled={busy} aria-label="To‘lov tarixini yangilash" onClick={() => void refresh()}><Icon name="refresh" size={18} /></button></div>
      {!history.orders.length ? <p className="muted">Hali sinov to‘lovlari yo‘q.</p> : <ol className="payment-history">{orderPage.items.map(order => <li key={order.id}><div className="payment-row-heading"><strong>⭐ {order.amount}</strong><span className={'payment-status payment-' + order.status}>{labels[order.status]}</span></div><details className="payment-receipt"><summary>Buyurtma raqami</summary><p className="payment-reference">{order.id}</p></details><small>{new Date(order.created_at * 1000).toLocaleString('uz-UZ')} · {order.environment === 'test' ? 'Test serveri' : 'Jonli muhit'}</small><div className="actions">
        {history.settings.enabled && nativeCheckout && order.status === 'invoice_ready' && order.invoice_url && <button className="secondary" disabled={busy} onClick={() => open(order)}>Hisobni ochish<Icon name="arrow" size={16} /></button>}
        {(order.status === 'paid' || order.status === 'refund_pending') && <button className="secondary" disabled={busy} onClick={() => void refund(order)}>{order.status === 'paid' ? 'Starsni qaytarish' : 'Qaytarishni qayta urinish'}<Icon name="refresh" size={16} /></button>}
      </div></li>)}</ol>}
      <PageControls page={orderPage.page} pages={orderPage.pages} onChange={orderPage.setPage} label="Stars to‘lovlari sahifalari" />
      {!!history.additional_payments.length && <Alert tone="warning">Mos kelmagan yoki ortiqcha {history.additional_payments.length} ta to‘lov qayd etilgan: {history.additional_payments.filter(item => item.status === 'refunded').length} tasi qaytarilgan. Qolganlari avtomatik qaytariladi; yordam uchun murojaat qiling.</Alert>}
      {history.settings.support_url && <a className="payment-support" href={history.settings.support_url} target="_blank" rel="noreferrer"><Icon name="help" size={17} />To‘lov bo‘yicha yordam</a>}
    </>}
  </section>;
}
