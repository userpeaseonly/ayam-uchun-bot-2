import { useEffect, useRef, useState, type ReactNode } from 'react';
import { api, linkedTest } from './api';
import type { CatalogPage, Profile, StudentTest, TestSummary, Visibility } from './types';
import { Alert, Badge, EmptyState, Icon, Loading, useTelegramBack } from './ui';

const errorMessage = (error: unknown) => error instanceof Error ? error.message : 'Amal bajarilmadi.';
export const visibilityLabel = (value: Visibility) => value === 'public' ? 'Ochiq' : 'Havola orqali';
export const sessionDate = (value: string) => new Date(value.replace(' ', 'T') + (value.includes('Z') ? '' : 'Z')).toLocaleDateString('uz-UZ');

export function PublisherProfile({ profile, suggestedName, saved }: { profile: Profile | null; suggestedName: string; saved(profile: Profile): void }) {
  const [name, setName] = useState(profile?.full_name || suggestedName);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  return <section className="card publisher-profile"><details open={!profile}><summary><span><Icon name="users" size={19} />{profile ? profile.full_name : 'Nashr qilish uchun ismingizni kiriting'}</span><Icon name="edit" size={17} /></summary><p>Testlaringizda ism va familiyangiz ko‘rinadi. Barcha o‘qituvchilar test yuklashi mumkin.</p><form onSubmit={async event => {
    event.preventDefault(); setBusy(true); setError(''); setNotice('');
    try { const result = await api<Profile>('/profile', { method: 'PUT', body: JSON.stringify({ full_name: name }) }); saved(result); setNotice('Profil saqlandi.'); }
    catch (error) { setError(errorMessage(error)); } finally { setBusy(false); }
  }}><label className="field">To‘liq ism va familiya<input autoComplete="name" value={name} maxLength={150} required onChange={event => setName(event.target.value)} placeholder="Masalan, Dilnoza Karimova" /></label><button disabled={busy}>{busy ? 'Saqlanmoqda…' : 'Profilni saqlash'}<Icon name="check" size={17} /></button></form>{error && <Alert>{error}</Alert>}{notice && <p role="status">{notice}</p>}</details></section>;
}

export function PublicationFields({ visibility, subject, change }: { visibility: Visibility; subject: string; change(visibility: Visibility, subject: string): void }) {
  return <div className="publication-fields"><label className="field">Ko‘rinish<select value={visibility} onChange={event => change(event.target.value as Visibility, subject)}><option value="public">Ochiq — katalogda ko‘rinadi</option><option value="unlisted">Havola orqali — katalogda ko‘rinmaydi</option></select></label><label className="field">Fan (ixtiyoriy)<input value={subject} maxLength={80} placeholder="Masalan, Ona tili" onChange={event => change(visibility, event.target.value)} /></label><p className="field-hint">{visibility === 'public' ? 'Istalgan o‘quvchi katalogdan topib, test topshirishi mumkin.' : 'Havolani olgan istalgan o‘quvchi test topshirishi mumkin.'}</p></div>;
}

export function ListingSettings({ test, saved }: { test: TestSummary; saved(): Promise<void> }) {
  const [visibility, setVisibility] = useState(test.visibility);
  const [subject, setSubject] = useState(test.subject);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  useEffect(() => { if (!dirty) { setVisibility(test.visibility); setSubject(test.subject); } }, [test.visibility, test.subject, dirty]);
  return <fieldset className="editor-fields" disabled={busy}><PublicationFields visibility={visibility} subject={subject} change={(value, topic) => { setVisibility(value); setSubject(topic); setDirty(true); setNotice(''); }} />{error && <Alert>{error}</Alert>}{notice && <p role="status">{notice}</p>}<button className="secondary" disabled={!dirty} onClick={async () => {
    setBusy(true); setError('');
    try { await api('/teacher/tests/' + test.id + '/listing', { method: 'POST', body: JSON.stringify({ visibility, subject }) }); await saved(); setDirty(false); setNotice('Ko‘rinish saqlandi.'); }
    catch (error) { setError(errorMessage(error)); } finally { setBusy(false); }
  }}>Ko‘rinishni saqlash</button></fieldset>;
}

export function StudentCatalog({ firstName, renderAttempt }: { firstName: string; renderAttempt(test: StudentTest, back: () => void): ReactNode }) {
  const [scope, setScope] = useState<'public' | 'drafts' | 'results'>('public');
  const [query, setQuery] = useState('');
  const [subject, setSubject] = useState('');
  const [page, setPage] = useState<CatalogPage>({ items: [], subjects: [], next_cursor: null });
  const [selected, setSelected] = useState<string | null>(() => linkedTest(location.search, window.Telegram?.WebApp.initDataUnsafe?.start_param));
  const [attempt, setAttempt] = useState<StudentTest | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(true);
  const generation = useRef(0);
  async function load(more = false) {
    const current = ++generation.current;
    setBusy(true); setError('');
    const params = new URLSearchParams({ scope, q: query, subject });
    if (more && page.next_cursor) params.set('before', String(page.next_cursor));
    try {
      const result = await api<CatalogPage>('/catalog?' + params);
      if (generation.current === current) setPage(previous => ({ ...result, items: more ? [...previous.items, ...result.items] : result.items }));
    } catch (error) { if (generation.current === current) setError(errorMessage(error)); }
    finally { if (generation.current === current) setBusy(false); }
  }
  useEffect(() => {
    ++generation.current; setBusy(true); setPage({ items: [], subjects: page.subjects, next_cursor: null });
    const timer = setTimeout(() => void load(), 250);
    return () => { clearTimeout(timer); ++generation.current; };
  }, [scope, query, subject, selected]);
  useEffect(() => { window.scrollTo({ top: 0 }); }, [selected, attempt?.id]);
  function catalog() { setAttempt(null); setSelected(null); }
  if (attempt) return renderAttempt(attempt, () => setAttempt(null));
  if (selected) return <TestIntroduction key={selected} handle={selected} back={catalog} start={setAttempt} />;
  return <>
    <section className="welcome-banner catalog-welcome"><div><span className="eyebrow">BARCHA UCHUN OCHIQ</span><p className="welcome-greeting">Assalomu alaykum, {firstName}!</p><h1>Bilimingizni sinang.</h1><p>Turli o‘qituvchilarning testlarini toping.<br />O‘rganing, mashq qiling va natijangizni kuzating.</p><span className="welcome-tag"><Icon name="book" size={15} />Hozir barcha testlar bepul</span></div><div className="brand-illustration" aria-hidden="true"><img src="/basirat-logo.png" alt="" /></div></section>
    <nav className="tabs catalog-tabs" aria-label="O‘quvchi bo‘limlari">{([['public', 'Testlar katalogi'], ['drafts', 'Boshlangan testlar'], ['results', 'Natijalarim']] as const).map(([value, label]) => <button key={value} className={scope === value ? 'selected' : ''} aria-pressed={scope === value} onClick={() => { setScope(value); setQuery(''); setSubject(''); }}>{label}</button>)}</nav>
    <section className="catalog-toolbar"><label className="search-field"><Icon name="search" size={18} /><input value={query} onChange={event => setQuery(event.target.value)} aria-label="Test yoki o‘qituvchini qidirish" placeholder="Test, fan yoki o‘qituvchi ismi…" /></label><label className="catalog-subject">Fan<select aria-label="Fan bo‘yicha saralash" value={subject} onChange={event => setSubject(event.target.value)}><option value="">Barcha fanlar</option>{page.subjects.map(item => <option key={item}>{item}</option>)}</select></label><button className="icon-button" aria-label="Katalogni yangilash" disabled={busy} onClick={() => void load()}><Icon name="refresh" /></button></section>
    {error && <Alert>{error}<button className="quiet" onClick={() => void load()}>Qayta urinish</button></Alert>}
    {busy && !page.items.length ? <Loading label="Testlar yuklanmoqda…" /> : !page.items.length && !error ? <section className="card"><EmptyState icon="book" title={scope === 'results' ? 'Natijalaringiz shu yerda bo‘ladi' : scope === 'drafts' ? 'Boshlangan testlar yo‘q' : 'Test topilmadi'}>{scope === 'public' ? 'Boshqa nom bilan qidiring yoki o‘qituvchi yuborgan havolani oching.' : 'Katalogdan test tanlang. Javoblar va natijalar hisobingizda saqlanadi.'}</EmptyState></section> : <div className="catalog-grid">{page.items.map(test => <button className="card catalog-card" key={test.id} onClick={() => setSelected(test.public_id)}><div className="section-heading"><span className="catalog-subject-tag">{test.subject || 'Umumiy test'}</span><Badge status={test.status} /></div><h2>{test.title}</h2><p className="publisher-name"><Icon name="users" size={17} />{test.publisher_name}</p><div className="catalog-meta"><span>{test.total_questions} ta savol</span><span>{sessionDate(test.created_at)} · #{test.id}</span></div><div className="catalog-card-bottom"><span>{test.submission_id ? test.score == null ? 'Yakuniy ball kutilmoqda' : `${test.score} ball · ${test.rank}-o‘rin` : test.draft_revision != null ? 'Davom ettirish' : 'Test bilan tanishish'}</span><Icon name="arrow" size={18} /></div></button>)}</div>}
    {page.next_cursor && <div className="catalog-more"><button className="secondary" disabled={busy} onClick={() => void load(true)}>{busy ? 'Yuklanmoqda…' : 'Yana ko‘rsatish'}</button></div>}
    <p className="catalog-note"><Icon name="shield" size={17} />Javoblaringiz va shaxsiy natijalaringiz faqat siz hamda test egasiga ko‘rinadi.</p>
  </>;
}

function TestIntroduction({ handle, back, start }: { handle: string; back(): void; start(test: StudentTest): void }) {
  const [test, setTest] = useState<TestSummary | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useTelegramBack(back);
  async function load() {
    setError('');
    try { setTest(await api<TestSummary>('/tests/' + encodeURIComponent(handle) + '/intro')); }
    catch (error) { setError(errorMessage(error)); }
  }
  useEffect(() => { void load(); }, [handle]);
  async function open() {
    setBusy(true); setError('');
    try { start(await api<StudentTest>('/tests/' + encodeURIComponent(handle))); }
    catch (error) { setError(errorMessage(error)); } finally { setBusy(false); }
  }
  return <><button className="back-link" onClick={back}><Icon name="back" size={17} />Testlar katalogi</button>{error && <Alert>{error}<button className="quiet" onClick={() => void load()}>Qayta urinish</button></Alert>}{test ? <section className="card test-introduction"><div className="actions"><span className="eyebrow">{test.subject || 'BASIRAT TESTLAR'}</span><Badge status={test.status} /><span className="muted">{visibilityLabel(test.visibility)}</span></div><h1>{test.title}</h1><p className="publisher-name"><Icon name="users" size={21} /><strong>{test.publisher_name}</strong></p><p className="muted">{sessionDate(test.created_at)} · {test.id}-sessiya</p><div className="intro-facts"><div><strong>{test.total_questions}</strong><span>ta savol</span></div><div><strong>{test.open_questions_count}</strong><span>ta ochiq savol</span></div><div><strong>Bepul</strong><span>hozirgi kirish</span></div></div><ol className="intro-rules"><li>Savollar orasida erkin o‘ting. Javoblaringiz avtomatik saqlanadi.</li><li>Har bir sessiyaga bir marta javob topshirasiz. Tasdiqlashdan oldin tekshiring.</li><li>To‘g‘ri va noto‘g‘ri javoblar topshirgach ko‘rinadi. Yakuniy ball va reyting o‘qituvchi sessiyani yakunlagach ochiladi.</li></ol>{test.status === 'finished' && !test.submission_id ? <Alert tone="warning">Bu sessiya yakunlangan. Yangi javoblar qabul qilinmaydi.</Alert> : <button className="full-width" disabled={busy} onClick={() => void open()}>{busy ? 'Ochilmoqda…' : test.submission_id ? 'Natijamni ko‘rish' : test.draft_revision != null ? 'Davom ettirish' : 'Testni boshlash'}<Icon name="arrow" size={18} /></button>}</section> : !error && <Loading label="Test ma’lumotlari yuklanmoqda…" />}</>;
}
