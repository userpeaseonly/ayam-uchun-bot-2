import { useEffect, useRef, useState, type ReactNode } from 'react';
import { api, post } from './api';
import type { AttemptTimer, CatalogPage, Profile, StudentTest, Submission, TestSummary, Visibility } from './types';
import { Alert, Badge, EmptyState, Icon, Loading, PageHeading, useTelegramBack } from './ui';
import { useAttemptTimer } from './useAttemptTimer';
import { formatCountdown } from './timer';

const errorMessage = (error: unknown) => error instanceof Error ? error.message : 'Amal bajarilmadi.';
export const visibilityLabel = (value: Visibility) => value === 'public' ? 'Ochiq' : 'Havola orqali';
export const sessionDate = (value: string) => new Date(value.replace(' ', 'T') + (value.includes('Z') ? '' : 'Z')).toLocaleDateString('uz-UZ');

export function PublisherProfile({ profile, suggestedName, saved, prompt = false }: { profile: Profile | null; suggestedName: string; saved(profile: Profile): void; prompt?: boolean }) {
  const [name, setName] = useState(profile?.full_name || suggestedName);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  return <section className="card publisher-profile"><details open={prompt && !profile}><summary><span><Icon name="users" size={19} />{profile ? 'Nashr qiluvchi: ' + profile.full_name : 'Nashr qiluvchi profili'}</span><Icon name="edit" size={17} /></summary><p>Bu ism testlaringizda ko‘rinadi.</p><form onSubmit={async event => {
    event.preventDefault(); setBusy(true); setError(''); setNotice('');
    try { const result = await api<Profile>('/profile', { method: 'PUT', body: JSON.stringify({ full_name: name }) }); saved(result); setNotice('Profil saqlandi.'); }
    catch (error) { setError(errorMessage(error)); } finally { setBusy(false); }
  }}><label className="field">Ism va familiya<input autoComplete="name" value={name} maxLength={150} required onChange={event => setName(event.target.value)} placeholder="Masalan, Dilnoza Karimova" /></label><button disabled={busy}>{busy ? 'Saqlanmoqda…' : 'Saqlash'}<Icon name="check" size={17} /></button></form>{error && <Alert>{error}</Alert>}{notice && <p role="status">{notice}</p>}</details></section>;
}

export function PublicationFields({ visibility, subject, duration, change }: { visibility: Visibility; subject: string; duration: number | null; change(visibility: Visibility, subject: string, duration: number | null): void }) {
  return <div className="publication-fields"><label className="field">Ko‘rinish<select value={visibility} onChange={event => change(event.target.value as Visibility, subject, duration)}><option value="public">Ochiq — katalogda ko‘rinadi</option><option value="unlisted">Havola orqali — katalogda ko‘rinmaydi</option></select></label><label className="field">Fan (ixtiyoriy)<input value={subject} maxLength={80} placeholder="Masalan, Ona tili" onChange={event => change(visibility, event.target.value, duration)} /></label><p className="field-hint">{visibility === 'public' ? 'Katalogda barcha uchun ochiq.' : 'Faqat havola orqali topiladi.'}</p><label className="field">Vaqt chegarasi (daqiqa)<input type="number" min={1} max={1440} step={1} inputMode="numeric" value={duration ?? ''} placeholder="Masalan, 60" onChange={event => change(visibility, subject, event.target.value === '' ? null : Number(event.target.value))} /></label><p className="field-hint">Bo‘sh — cheklanmagan. Boshlagach vaqt to‘xtamaydi; tugaganda javoblar avtomatik topshiriladi. O‘quvchi boshlagach muddat o‘zgarmaydi.</p></div>;
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
  const timed = test.duration_minutes !== null;
  return <button className={'started-card ' + (timed ? 'started-timed' : 'started-saved')} onClick={open}>
    <span className="started-symbol"><Icon name={timed ? 'clock' : 'edit'} size={20} /></span>
    <span className="started-copy"><span className="started-label">{timed ? 'Vaqt to‘xtamaydi' : 'Davom ettirish'}</span><strong>{test.title}</strong><span className="started-publisher">{test.publisher_name}</span></span>
    <span className="started-action">{status ? <ResumeClock handle={test.public_id} status={status} settled={settled} /> : <span>{timed ? 'Tekshirilmoqda…' : 'Saqlangan'}</span>}<Icon name="arrow" size={17} /></span>
  </button>;
}

function ResumeClock({ handle, status, settled }: { handle: string; status: { timer: AttemptTimer | null; submission: Submission | null }; settled(): void }) {
  const clock = useAttemptTimer({ public_id: handle, timer: status.timer }, null, settled);
  return <span aria-label={clock.seconds === null ? 'Javoblar saqlangan' : 'Qolgan vaqt: ' + formatCountdown(clock.seconds)} className={'resume-time ' + (clock.seconds !== null && clock.seconds <= 60 ? 'urgent' : '')}>{clock.seconds === null ? 'Saqlangan' : clock.expired ? 'Vaqt tugadi' : formatCountdown(clock.seconds)}{clock.problem && <span title={clock.problem}> · Ulanish kutilmoqda</span>}</span>;
}

export function StudentCatalog({ firstName, section, initialHandle, onFocus, renderAttempt }: { firstName: string; section: 'tests' | 'results'; initialHandle: string | null; onFocus(value: boolean): void; renderAttempt(test: StudentTest, back: () => void, done: () => void): ReactNode }) {
  const scope = section === 'results' ? 'results' : 'public';
  const [query, setQuery] = useState('');
  const [page, setPage] = useState<CatalogPage>({ items: [], subjects: [], next_cursor: null });
  const [cursors, setCursors] = useState<(number | null)[]>([null]);
  const [pageIndex, setPageIndex] = useState(0);
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
  async function load() {
    const current = ++generation.current;
    setBusy(true); setError('');
    const params = new URLSearchParams({ scope, q: query, limit: '2' });
    const before = cursors[pageIndex];
    if (before) params.set('before', String(before));
    try {
      const result = await api<CatalogPage>('/catalog?' + params);
      if (generation.current === current) setPage(result);
    } catch (error) { if (generation.current === current) setError(errorMessage(error)); }
    finally { if (generation.current === current) setBusy(false); }
  }
  const refreshCatalog = useRef(load); refreshCatalog.current = load;
  async function loadResumable(more = false) {
    const current = ++resumeGeneration.current; setResumeBusy(true);
    try {
      const result = await api<CatalogPage>('/catalog?scope=drafts' + (more && resumeCursor ? '&before=' + resumeCursor : ''));
      if (current !== resumeGeneration.current) return;
      setResumable(previous => more ? [...previous, ...result.items] : result.items); setResumeCursor(result.next_cursor); setResumeError('');
    } catch (error) { if (current === resumeGeneration.current) setResumeError(errorMessage(error)); }
    finally { if (current === resumeGeneration.current) setResumeBusy(false); }
  }
  function search(value: string) { setQuery(value); setPageIndex(0); setCursors([null]); }
  useEffect(() => {
    if (previousSection.current === section) return;
    previousSection.current = section; setSelected(null); setAttempt(null); search('');
  }, [section]);
  useEffect(() => {
    onFocus(Boolean(selected));
    return () => onFocus(false);
  }, [Boolean(selected), onFocus]);
  useEffect(() => {
    if (selected) return;
    ++generation.current; setBusy(true); setPage({ items: [], subjects: [], next_cursor: null });
    const timer = setTimeout(() => void load(), 250);
    return () => { clearTimeout(timer); ++generation.current; };
  }, [scope, query, pageIndex, selected]);
  useEffect(() => {
    if (selected || section !== 'tests') return;
    void loadResumable();
    const refresh = () => { if (document.visibilityState === 'visible') { void loadResumable(); void refreshCatalog.current(); } };
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
  if (opening) return <Loading label="Test ochilmoqda…" />;
  if (attempt) return <div className="student-test-view">{renderAttempt(attempt, () => setAttempt(null), catalog)}</div>;
  if (selected) return <div className="student-test-view">{openError && <Alert>{openError}</Alert>}<TestIntroduction key={selected} handle={selected} back={catalog} start={setAttempt} /></div>;
  const featured = resumable.find(test => test.duration_minutes !== null) || resumable[0];
  const otherStarted = resumable.filter(test => test.id !== featured?.id);
  const settled = () => { void loadResumable(); void load(); };
  const personalMessage = featured?.duration_minutes != null ? `${firstName}, sinov vaqti davom etmoqda.` : featured ? `${firstName}, mashqni davom ettiramizmi?` : `${firstName}, navbatdagi sinovga tayyormisiz?`;
  return <div className={section === 'tests' ? 'catalog-home' : 'catalog-results'}>
    {section === 'tests' ? <div className="catalog-greeting"><span className="greeting-symbol"><Icon name="spark" size={20} /></span><h1>{personalMessage}</h1></div> : <PageHeading icon="chart" title="Natijalarim" />}
    <section className="catalog-toolbar" aria-label="Test qidirish"><label className="search-field"><Icon name="search" size={18} /><input type="search" value={query} onChange={event => search(event.target.value)} aria-label="Test yoki ustozni qidirish" placeholder="Test yoki ustozni qidirish" /></label></section>
    {section === 'tests' && <>
      {resumeError && <Alert tone="warning">Boshlangan testlar yuklanmadi.<button className="quiet" onClick={() => void loadResumable()}>Qayta urinish</button></Alert>}
      {featured && <section className="started-tests" aria-label="Boshlangan testlar"><ResumeCard key={featured.id} test={featured} open={() => void resume(featured.public_id)} settled={settled} />
        {(!!otherStarted.length || resumeCursor) && <details className="other-started"><summary>{otherStarted.length ? `Yana ${otherStarted.length}${resumeCursor ? '+' : ''} ta boshlangan test` : 'Boshqa boshlangan testlar'}<Icon name="chevron" size={14} /></summary><div>{otherStarted.map(test => <ResumeCard key={test.id} test={test} open={() => void resume(test.public_id)} settled={settled} />)}{resumeCursor && <button className="quiet" disabled={resumeBusy} onClick={() => void loadResumable(true)}>Yana ko‘rsatish</button>}</div></details>}
      </section>}
      <div className="catalog-caption"><h2>{query ? 'Qidiruv natijalari' : 'Sinovlar'}</h2></div>
    </>}
    {error && <Alert>{error}<button className="quiet" onClick={() => void load()}>Qayta urinish</button></Alert>}
    {busy ? <Loading label="Testlar yuklanmoqda…" /> : !page.items.length && !error ? <section className="card"><EmptyState icon={scope === 'results' ? 'chart' : 'book'} title={scope === 'results' ? 'Hali natijalar yo‘q' : 'Test topilmadi'}>{query ? 'Boshqa nom bilan qidiring.' : scope === 'public' ? 'Testlar shu yerda ko‘rinadi.' : 'Topshirgan testlaringiz shu yerda ko‘rinadi.'}</EmptyState></section> : <div className="catalog-grid" aria-label={section === 'tests' ? 'Testlar ro‘yxati' : 'Natijalar ro‘yxati'}>{page.items.map(test => <button className="card catalog-card" key={test.id} onClick={() => { if (test.submission_id || test.draft_revision != null) void resume(test.public_id); else setSelected(test.public_id); }}>
      {scope === 'results' && <span className={'badge ' + (test.score == null ? 'status-processing' : 'status-published')}>{test.score == null ? 'Ball kutilmoqda' : 'Natija tayyor'}</span>}
      <h2>{test.title}</h2><p className="publisher-name"><Icon name="users" size={15} />{test.publisher_name}</p>
      {scope === 'results' && test.score != null && <div className="result-card-score"><strong>{test.score}<small> ball</small></strong><span>{test.rank}-o‘rin</span></div>}
      <div className="catalog-card-bottom"><div className="catalog-meta"><span><Icon name="file" size={14} />{test.total_questions} savol</span><span><Icon name="clock" size={14} />{test.duration_minutes ? `${test.duration_minutes} daq.` : 'Cheklanmagan'}</span></div><span className="catalog-card-action">{test.submission_id ? test.score == null ? 'Javoblar' : 'Natijani ko‘rish' : test.draft_revision != null ? test.duration_minutes !== null ? 'Qaytish' : 'Davom etish' : 'Boshlash'}<Icon name="arrow" size={16} /></span></div>
    </button>)}</div>}
    {(pageIndex > 0 || page.next_cursor) && <nav className="catalog-pagination" aria-label="Test sahifalari"><button className="secondary" disabled={busy || pageIndex === 0} onClick={() => setPageIndex(value => value - 1)}><Icon name="back" size={16} />Oldingi</button><span aria-live="polite">{pageIndex + 1}-sahifa</span><button className="secondary" disabled={busy || !page.next_cursor} onClick={() => { if (page.next_cursor) { setCursors(previous => [...previous.slice(0, pageIndex + 1), page.next_cursor]); setPageIndex(value => value + 1); } }}>Keyingi<Icon name="arrow" size={16} /></button></nav>}
  </div>;
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
      <div className="intro-status"><Badge status={test.status} /></div>
      <h1>{test.title}</h1><p className="publisher-name"><Icon name="users" size={19} />{test.publisher_name}</p>
      <div className="intro-facts"><div><Icon name="file" /><strong>{test.total_questions}</strong><span>ta savol</span></div><div><Icon name="clock" /><strong>{test.duration_minutes ?? '∞'}</strong><span>{test.duration_minutes ? 'daqiqa' : 'vaqt cheklanmagan'}</span></div></div>
      {!test.submission_id && <>
        {test.duration_minutes !== null ? <Alert tone="warning">{test.draft_revision != null ? 'Vaqt davom etmoqda.' : 'Vaqt «Testni boshlash» bosilganda boshlanadi.'} Ilovani yopish soatni to‘xtatmaydi. Muddat tugaganda saqlangan javoblar topshiriladi.</Alert> : <p className="field-hint">Vaqt cheklanmagan. Keyinroq davom ettirish mumkin.</p>}
        <ul className="intro-checklist"><li><Icon name="check" size={18} /><span>Javoblar avtomatik saqlanadi.</span></li><li><Icon name="shield" size={18} /><span>Bir marta topshirasiz.</span></li><li><Icon name="chart" size={18} /><span>Javoblar topshirgach, ball va o‘rin test yakunlangach ko‘rinadi.{test.open_questions_count > 0 && ` ${test.open_questions_count} ta ochiq javob tekshiriladi.`}</span></li></ul>
      </>}
      {test.status === 'finished' && !test.submission_id ? <Alert tone="warning">Bu sessiya yakunlangan. Yangi javoblar qabul qilinmaydi.</Alert> : <button className="full-width" disabled={busy} onClick={() => void open()}>{busy ? 'Ochilmoqda…' : test.submission_id ? 'Natijamni ko‘rish' : test.draft_revision != null ? test.duration_minutes !== null ? 'Testga qaytish' : 'Davom ettirish' : 'Testni boshlash'}<Icon name="arrow" size={18} /></button>}
    </section> : !error && <Loading label="Test ma’lumotlari yuklanmoqda…" />}
  </>;
}
