import { useEffect, useRef, useState, type ReactNode } from 'react';
import { api, post } from './api';
import type { AttemptTimer, CatalogPage, Profile, StudentTest, Submission, TestSummary, Visibility } from './types';
import { Alert, Badge, EmptyState, Icon, Loading, useTelegramBack } from './ui';
import { useAttemptTimer } from './useAttemptTimer';
import { formatCountdown } from './timer';

const errorMessage = (error: unknown) => error instanceof Error ? error.message : 'Amal bajarilmadi.';
export const visibilityLabel = (value: Visibility) => value === 'public' ? 'Ochiq' : 'Havola orqali';
export const sessionDate = (value: string) => new Date(value.replace(' ', 'T') + (value.includes('Z') ? '' : 'Z')).toLocaleDateString('uz-UZ');

export function PublisherProfile({ profile, suggestedName, saved }: { profile: Profile | null; suggestedName: string; saved(profile: Profile): void }) {
  const [name, setName] = useState(profile?.full_name || suggestedName);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  return <section className="card publisher-profile"><details open={!profile}><summary><span><Icon name="users" size={19} />{profile ? 'Nashr qiluvchi ismi: ' + profile.full_name : 'Nashr qilish uchun ismingizni kiriting'}</span><Icon name="edit" size={17} /></summary><p>Testlaringizda ism va familiyangiz ko‘rinadi. Barcha o‘qituvchilar test yuklashi mumkin.</p><form onSubmit={async event => {
    event.preventDefault(); setBusy(true); setError(''); setNotice('');
    try { const result = await api<Profile>('/profile', { method: 'PUT', body: JSON.stringify({ full_name: name }) }); saved(result); setNotice('Profil saqlandi.'); }
    catch (error) { setError(errorMessage(error)); } finally { setBusy(false); }
  }}><label className="field">To‘liq ism va familiya<input autoComplete="name" value={name} maxLength={150} required onChange={event => setName(event.target.value)} placeholder="Masalan, Dilnoza Karimova" /></label><button disabled={busy}>{busy ? 'Saqlanmoqda…' : 'Profilni saqlash'}<Icon name="check" size={17} /></button></form>{error && <Alert>{error}</Alert>}{notice && <p role="status">{notice}</p>}</details></section>;
}

export function PublicationFields({ visibility, subject, duration, change }: { visibility: Visibility; subject: string; duration: number | null; change(visibility: Visibility, subject: string, duration: number | null): void }) {
  return <div className="publication-fields"><label className="field">Ko‘rinish<select value={visibility} onChange={event => change(event.target.value as Visibility, subject, duration)}><option value="public">Ochiq — katalogda ko‘rinadi</option><option value="unlisted">Havola orqali — katalogda ko‘rinmaydi</option></select></label><label className="field">Fan (ixtiyoriy)<input value={subject} maxLength={80} placeholder="Masalan, Ona tili" onChange={event => change(visibility, event.target.value, duration)} /></label><p className="field-hint">{visibility === 'public' ? 'Istalgan o‘quvchi katalogdan topib, test topshirishi mumkin.' : 'Havolani olgan istalgan o‘quvchi test topshirishi mumkin.'}</p><label className="field">Vaqt chegarasi (daqiqa)<input type="number" min={1} max={1440} step={1} inputMode="numeric" value={duration ?? ''} placeholder="Masalan, 60" onChange={event => change(visibility, subject, event.target.value === '' ? null : Number(event.target.value))} /></label><p className="field-hint">Bo‘sh qoldirilsa, vaqt cheklanmaydi. Vaqt o‘quvchi testni boshlaganda hisoblanadi; tugagach saqlangan javoblar avtomatik topshiriladi. O‘quvchilar boshlagach vaqtni o‘zgartirib bo‘lmaydi.</p></div>;
}

export function ListingSettings({ test, saved }: { test: TestSummary; saved(): Promise<void> }) {
  const [visibility, setVisibility] = useState(test.visibility);
  const [subject, setSubject] = useState(test.subject);
  const [duration, setDuration] = useState(test.duration_minutes);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  useEffect(() => { if (!dirty) { setVisibility(test.visibility); setSubject(test.subject); setDuration(test.duration_minutes); } }, [test.visibility, test.subject, test.duration_minutes, dirty]);
  return <fieldset className="editor-fields" disabled={busy}><PublicationFields visibility={visibility} subject={subject} duration={duration} change={(value, topic, minutes) => { setVisibility(value); setSubject(topic); setDuration(minutes); setDirty(true); setNotice(''); }} />{error && <Alert>{error}</Alert>}{notice && <p role="status">{notice}</p>}<button className="secondary" disabled={!dirty} onClick={async () => {
    setBusy(true); setError('');
    try { await api('/teacher/tests/' + test.id + '/listing', { method: 'POST', body: JSON.stringify({ visibility, subject, duration_minutes: duration }) }); await saved(); setDirty(false); setNotice('Sozlamalar saqlandi.'); }
    catch (error) { setError(errorMessage(error)); } finally { setBusy(false); }
  }}>Sozlamalarni saqlash</button></fieldset>;
}

function ResumeCard({ test, open, settled }: { test: TestSummary; open(): void; settled(): void }) {
  const onSettled = useRef(settled); onSettled.current = settled;
  const [status, setStatus] = useState<{ timer: AttemptTimer | null; submission: Submission | null } | null>(null);
  useEffect(() => {
    let active = true;
    void api<{ timer: AttemptTimer | null; submission: Submission | null }>('/tests/' + test.public_id + '/timer').then(value => {
      if (!active) return;
      if (value.submission) onSettled.current(); else setStatus(value);
    }).catch(() => {});
    return () => { active = false; };
  }, [test.public_id]);
  return <article className="resume-card"><div className="section-heading"><span className="eyebrow"><Icon name="edit" size={15} />BOSHLANGAN TEST</span>{status ? <ResumeClock handle={test.public_id} status={status} settled={settled} /> : <span className="muted">Javoblar hisobingizda saqlanadi</span>}</div><h3>{test.title}</h3><p>{test.publisher_name}</p><button onClick={open}>Davom ettirish<Icon name="arrow" size={17} /></button></article>;
}

function ResumeClock({ handle, status, settled }: { handle: string; status: { timer: AttemptTimer | null; submission: Submission | null }; settled(): void }) {
  const clock = useAttemptTimer({ public_id: handle, timer: status.timer }, null, settled);
  return <span aria-label={clock.seconds === null ? 'Javoblar saqlangan' : 'Qolgan vaqt: ' + formatCountdown(clock.seconds)} className={'resume-time ' + (clock.seconds !== null && clock.seconds <= 60 ? 'urgent' : '')}><Icon name={clock.seconds === null ? 'check' : 'clock'} size={16} />{clock.seconds === null ? 'Saqlangan' : clock.expired ? 'Vaqt tugadi' : formatCountdown(clock.seconds)}{clock.problem && <span> · Ulanish kutilmoqda</span>}</span>;
}

export function StudentCatalog({ firstName, section, initialHandle, onFocus, renderAttempt }: { firstName: string; section: 'tests' | 'results'; initialHandle: string | null; onFocus(value: boolean): void; renderAttempt(test: StudentTest, back: () => void, done: () => void): ReactNode }) {
  const scope = section === 'results' ? 'results' : 'public';
  const [query, setQuery] = useState('');
  const [subject, setSubject] = useState('');
  const [page, setPage] = useState<CatalogPage>({ items: [], subjects: [], next_cursor: null });
  const [resumable, setResumable] = useState<TestSummary[]>([]);
  const [resumeCursor, setResumeCursor] = useState<number | null>(null);
  const [resumeError, setResumeError] = useState('');
  const [resumeBusy, setResumeBusy] = useState(false);
  const [selected, setSelected] = useState<string | null>(initialHandle);
  const [attempt, setAttempt] = useState<StudentTest | null>(null);
  const [opening, setOpening] = useState(false);
  const [openError, setOpenError] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(true);
  const generation = useRef(0);
  const resumeGeneration = useRef(0);
  const previousSection = useRef(section);
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
  async function loadResumable(more = false) {
    const current = ++resumeGeneration.current; setResumeBusy(true);
    try {
      const result = await api<CatalogPage>('/catalog?scope=drafts' + (more && resumeCursor ? '&before=' + resumeCursor : ''));
      if (current !== resumeGeneration.current) return;
      setResumable(previous => more ? [...previous, ...result.items] : result.items); setResumeCursor(result.next_cursor); setResumeError('');
    } catch (error) { if (current === resumeGeneration.current) setResumeError(errorMessage(error)); }
    finally { if (current === resumeGeneration.current) setResumeBusy(false); }
  }
  useEffect(() => {
    if (previousSection.current === section) return;
    previousSection.current = section; setSelected(null); setAttempt(null); setQuery(''); setSubject('');
  }, [section]);
  useEffect(() => {
    onFocus(Boolean(selected));
    return () => onFocus(false);
  }, [Boolean(selected), onFocus]);
  useEffect(() => {
    if (selected) return;
    ++generation.current; setBusy(true); setPage(previous => ({ items: [], subjects: previous.subjects, next_cursor: null }));
    const timer = setTimeout(() => void load(), 250);
    return () => { clearTimeout(timer); ++generation.current; };
  }, [scope, query, subject, selected]);
  useEffect(() => {
    if (selected || section !== 'tests') return;
    void loadResumable();
    const refresh = () => { if (document.visibilityState === 'visible') void loadResumable(); };
    window.addEventListener('focus', refresh); document.addEventListener('visibilitychange', refresh);
    return () => { ++resumeGeneration.current; window.removeEventListener('focus', refresh); document.removeEventListener('visibilitychange', refresh); };
  }, [selected, section]);
  useEffect(() => { window.scrollTo({ top: 0 }); }, [selected, attempt?.id]);
  function catalog() { setAttempt(null); setSelected(null); setOpenError(''); }
  async function resume(handle: string) {
    setSelected(handle); setOpening(true); setOpenError('');
    try { setAttempt(await post<StudentTest>('/tests/' + encodeURIComponent(handle) + '/start')); }
    catch (error) { setOpenError(errorMessage(error)); }
    finally { setOpening(false); }
  }
  if (opening) return <Loading label="Saqlangan javoblaringiz ochilmoqda…" />;
  if (attempt) return renderAttempt(attempt, () => setAttempt(null), catalog);
  if (selected) return <>{openError && <Alert>{openError}</Alert>}<TestIntroduction key={selected} handle={selected} back={catalog} start={setAttempt} /></>;
  return <>
    <div className="student-heading"><div><p className="welcome-greeting">{section === 'tests' ? `Assalomu alaykum, ${firstName}!` : 'BARCHA TOPSHIRGAN TESTLARINGIZ'}</p><h1>{section === 'tests' ? 'Bugun nimani o‘rganamiz?' : 'Natijalarim'}</h1><p>{section === 'tests' ? 'Test tanlang va bilimingizni sinab ko‘ring.' : 'Javoblaringizni tekshiring va yakuniy natijalarni kuzating.'}</p></div>{section === 'tests' && <span className="free-label">Hozir barcha testlar bepul</span>}</div>
    {section === 'tests' && <>
      {resumeError && <Alert tone="warning">Boshlangan testlarni yuklab bo‘lmadi. {resumeError}<button className="quiet" onClick={() => void loadResumable()}>Qayta urinish</button></Alert>}
      {!!resumable.length && <section className="resume-section" aria-label="Boshlangan testlar"><div className="section-heading"><h2>To‘xtagan joyingizdan davom eting</h2><span className="muted">{resumable.length}{resumeCursor ? '+' : ''} ta test</span></div><div className="resume-grid">{resumable.map(test => <ResumeCard key={test.id} test={test} open={() => void resume(test.public_id)} settled={() => { void loadResumable(); void load(); }} />)}</div>{resumeCursor && <button className="quiet" disabled={resumeBusy} onClick={() => void loadResumable(true)}>Boshqa boshlangan testlar<Icon name="chevron" size={16} /></button>}</section>}
      <div className="section-heading catalog-section-heading"><h2>Testlar katalogi</h2><span className="muted">Barcha o‘qituvchilardan</span></div>
    </>}
    <section className="catalog-toolbar"><label className="search-field"><Icon name="search" size={18} /><input value={query} onChange={event => setQuery(event.target.value)} aria-label="Test yoki o‘qituvchini qidirish" placeholder="Test yoki o‘qituvchi ismini qidiring" /></label><label className="catalog-subject"><span className="sr-only">Fan bo‘yicha saralash</span><select aria-label="Fan bo‘yicha saralash" value={subject} onChange={event => setSubject(event.target.value)}><option value="">Barcha fanlar</option>{page.subjects.map(item => <option key={item}>{item}</option>)}</select></label><button className="icon-button" aria-label="Katalogni yangilash" disabled={busy} onClick={() => { void load(); if (section === 'tests') void loadResumable(); }}><Icon name="refresh" /></button></section>
    {error && <Alert>{error}<button className="quiet" onClick={() => void load()}>Qayta urinish</button></Alert>}
    {busy && !page.items.length ? <Loading label="Testlar yuklanmoqda…" /> : !page.items.length && !error ? <section className="card"><EmptyState icon={scope === 'results' ? 'chart' : 'book'} title={scope === 'results' ? 'Natijalaringiz shu yerda bo‘ladi' : 'Test topilmadi'}>{scope === 'public' ? 'Boshqa nom bilan qidiring yoki o‘qituvchi yuborgan havolani oching.' : query || subject ? 'Boshqa nom yoki fan bilan qidirib ko‘ring.' : 'Test topshirganingizdan keyin javoblar va yakuniy natijalarni shu yerda kuzatasiz.'}</EmptyState></section> : <div className="catalog-grid">{page.items.map(test => <button className="card catalog-card" key={test.id} onClick={() => { if (test.submission_id || test.draft_revision != null) void resume(test.public_id); else setSelected(test.public_id); }}><div className="section-heading"><span className="catalog-subject-tag">{test.subject || 'Umumiy test'}</span>{scope === 'results' ? <span className={'badge ' + (test.score == null ? 'status-processing' : 'status-published')}>{test.score == null ? 'Yakuniy natija kutilmoqda' : 'Natija tayyor'}</span> : <span className="catalog-access">Bepul</span>}</div><h2>{test.title}</h2><p className="publisher-name"><Icon name="users" size={17} />{test.publisher_name}</p><div className="catalog-meta"><span><Icon name="file" size={15} />{test.total_questions} ta savol</span><span><Icon name="clock" size={15} />{test.duration_minutes ? `${test.duration_minutes} daqiqa` : 'Vaqt cheklanmagan'}</span></div><div className="catalog-card-bottom"><span>{test.submission_id ? test.score == null ? 'Javoblarimni ko‘rish' : `${test.score} ball · ${test.rank}-o‘rin` : test.draft_revision != null ? 'Davom ettirish' : 'Test bilan tanishish'}</span><Icon name="arrow" size={18} /></div></button>)}</div>}
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
    try { start(await post<StudentTest>('/tests/' + encodeURIComponent(handle) + '/start')); }
    catch (error) { setError(errorMessage(error)); } finally { setBusy(false); }
  }
  return <>
    <button className="back-link" disabled={busy} onClick={back}><Icon name="back" size={17} />Testlarga qaytish</button>
    {error && <Alert>{error}<button className="quiet" onClick={() => void load()}>Qayta urinish</button></Alert>}
    {test ? <section className="card test-introduction">
      <div className="section-heading"><span className="catalog-subject-tag">{test.subject || 'Umumiy test'}</span><Badge status={test.status} /></div>
      <h1>{test.title}</h1><p className="publisher-name"><Icon name="users" size={19} />{test.publisher_name}</p>
      <div className="intro-facts"><div><Icon name="file" /><strong>{test.total_questions}</strong><span>ta savol</span></div><div><Icon name="clock" /><strong>{test.duration_minutes ?? '∞'}</strong><span>{test.duration_minutes ? 'daqiqa' : 'vaqt cheklanmagan'}</span></div><div><Icon name="book" /><strong>Bepul</strong><span>hozirgi kirish</span></div></div>
      {!test.submission_id && <>
        {test.duration_minutes && <Alert tone="warning">{test.draft_revision != null ? 'Vaqt davom etmoqda. Ilovani yopish vaqtni to‘xtatmaydi.' : 'Vaqt «Testni boshlash» tugmasini bosganingizdan so‘ng hisoblanadi. Ilovani yopish vaqtni to‘xtatmaydi.'} Vaqt tugaganda saqlangan javoblar avtomatik topshiriladi.</Alert>}
        <ul className="intro-checklist"><li><Icon name="check" size={18} /><span>Javoblar avtomatik saqlanadi. Savollar orasida erkin o‘ting.</span></li><li><Icon name="shield" size={18} /><span>Bir marta topshirasiz. Topshirishdan oldin javoblaringizni tekshiring.</span></li><li><Icon name="chart" size={18} /><span>Javoblar holati topshirgach ko‘rinadi. Ball va o‘rin o‘qituvchi testni yakunlagach ochiladi.{test.open_questions_count > 0 && ` ${test.open_questions_count} ta ochiq javob tekshirilishi kerak bo‘lishi mumkin.`}</span></li></ul>
      </>}
      {test.status === 'finished' && !test.submission_id ? <Alert tone="warning">Bu sessiya yakunlangan. Yangi javoblar qabul qilinmaydi.</Alert> : <button className="full-width" disabled={busy} onClick={() => void open()}>{busy ? 'Ochilmoqda…' : test.submission_id ? 'Natijamni ko‘rish' : test.draft_revision != null ? 'Davom ettirish' : 'Testni boshlash'}<Icon name="arrow" size={18} /></button>}
    </section> : !error && <Loading label="Test ma’lumotlari yuklanmoqda…" />}
  </>;
}
