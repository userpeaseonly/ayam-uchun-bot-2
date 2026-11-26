import React, { useCallback, useEffect, useId, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { api, post, questionAnswered, linkedImport, linkedTest, ApiError } from './api';
import type { Answers, ImportRecord, Passage, Question, Region, Results, StudentTest, Submission, TestDocument, TestSummary } from './types';
import { Alert, Badge, Brand, ConfirmationProvider, EmptyState, Guide, Icon, Loading, NavigationProvider, PageHeading, PageControls, usePagedList, useConfirmation, useExitGuard, useMediaQuery, useNavigation, useTelegramBack } from './ui';
import { PublicationFields, PublisherProfile, StudentCatalog, visibilityLabel, sessionDate, ListingSettings } from './platform';
import type { CatalogPage, Profile, Visibility, TeacherCounts } from './types';
import { useAttemptTimer } from './useAttemptTimer';
import { formatCountdown } from './timer';
import { PaymentPanel } from './payments';
import { VoiceExplanation, ExplanationPlayer } from './voice-explanation';
import { prepareReview, questionIssues } from './question-review';
import { ProtectedTest } from './content-protection';
import { SubmissionCelebration } from './submission-celebration';
import { BrowserLogin, BrowserPaymentPanel } from './browser-payments';
import './style.css';
import './workspace.css';
import './pages.css';
import './question-review.css';

const assetUrl = (id: string) => '/api/assets/' + id;
const message = (error: unknown) => error instanceof Error ? error.message : 'Amal bajarilmadi.';

// Only these formatting markers become elements; source HTML is never executed.
export function RichText({ text }: { text: string }) {
  const tokens = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*|<u>[\s\S]*?<\/u>)/g);
  return <span className="rich-text">{tokens.map((token, i) => token.startsWith('**') ? <strong key={i}>{token.slice(2, -2)}</strong> : token.startsWith('*') ? <em key={i}>{token.slice(1, -1)}</em> : token.startsWith('<u>') ? <u key={i}>{token.slice(3, -4)}</u> : <React.Fragment key={i}>{token}</React.Fragment>)}</span>;
}

function Field({ label, value, onChange, rows = 3, placeholder }: { label: string; value: string; onChange(value: string): void; rows?: number; placeholder?: string }) {
  const id = useId();
  return <div className="field"><label htmlFor={id}>{label}</label><textarea id={id} rows={rows} value={value} placeholder={placeholder} onChange={e => onChange(e.target.value)} /></div>;
}

function App() {
  return <ConfirmationProvider><NavigationProvider><Workspace /></NavigationProvider></ConfirmationProvider>;
}

type StudentPage = 'tests' | 'results' | 'profile';
const studentPages = [
  { id: 'tests', label: 'Testlar', icon: 'book' },
  { id: 'results', label: 'Natijalarim', icon: 'chart' },
  { id: 'profile', label: 'Profil', icon: 'users' },
] as const;

function Workspace() {
  const [identity, setIdentity] = useState<{ is_admin: boolean; show_payments: boolean; show_web_payments: boolean; session_audience: 'telegram' | 'browser'; can_teach: boolean; profile: Profile | null; user: { first_name: string; last_name?: string }; bot_import_url?: string | null } | null>(null);
  const [browserLogin, setBrowserLogin] = useState(false);
  const [error, setError] = useState('');
  const [mode, setMode] = useState<'student' | 'teacher'>('student');
  const [page, setPage] = useState<StudentPage>(() => !window.Telegram?.WebApp.initData && new URLSearchParams(location.search).has('payment') ? 'profile' : 'tests');
  const [focused, setFocused] = useState(false);
  const [guide, setGuide] = useState(false);
  const [loginAttempt, setLoginAttempt] = useState(0);
  const [switching, setSwitching] = useState(false);
  const [navigationError, setNavigationError] = useState('');
  const accountMenu = useRef<HTMLDetailsElement>(null);
  const entryImport = useRef(linkedImport(location.search));
  const entryTest = useRef(linkedTest(location.search, window.Telegram?.WebApp.initDataUnsafe?.start_param));
  const focusStudent = useCallback((value: boolean) => { setFocused(value); if (value) entryTest.current = null; }, []);
  const navigation = useNavigation();
  useEffect(() => { window.scrollTo({ top: 0 }); }, [mode, page]);
  useEffect(() => {
    const dismiss = (event: PointerEvent) => { if (accountMenu.current && !accountMenu.current.contains(event.target as Node)) accountMenu.current.open = false; };
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape' && accountMenu.current?.open) { accountMenu.current.open = false; accountMenu.current.querySelector('summary')?.focus(); } };
    document.addEventListener('pointerdown', dismiss); document.addEventListener('keydown', escape);
    return () => { document.removeEventListener('pointerdown', dismiss); document.removeEventListener('keydown', escape); };
  }, []);
  async function navigate(next: 'student' | 'teacher', destination: StudentPage = page) {
    if (accountMenu.current) accountMenu.current.open = false;
    if ((next === mode && destination === page && !focused) || switching) return;
    setSwitching(true); setNavigationError('');
    try { await navigation.leave(); if (mode === 'teacher') entryImport.current = null; setMode(next); setPage(destination); setFocused(false); }
    catch (error) { setNavigationError(message(error)); }
    finally { setSwitching(false); }
  }
  useEffect(() => {
    const telegram = window.Telegram?.WebApp;
    telegram?.ready(); telegram?.expand();
    if (telegram?.initData) { telegram.setHeaderColor?.('#fbf8fa'); telegram.setBackgroundColor?.('#fbf8fa'); }
    setError('');
    const login = async () => {
      try {
        let result;
        if (telegram?.initData) result = await post<typeof identity & object>('/session', { init_data: telegram.initData });
        else {
          try { result = await api<typeof identity & object>('/me'); }
          catch (error) {
            const browser = await api<{ enabled: boolean }>('/browser-config');
            if (browser.enabled) { setBrowserLogin(true); return; }
            throw error;
          }
        }
        if (!telegram?.initData && result.session_audience !== 'browser') {
          const browser = await api<{ enabled: boolean }>('/browser-config');
          if (browser.enabled) { setBrowserLogin(true); return; }
        }
        setIdentity(result);
        if (result.can_teach && (linkedImport(location.search) || new URLSearchParams(location.search).get('view') === 'teacher')) setMode('teacher');
      } catch (error) { setError(message(error)); }
    };
    void login();
  }, [loginAttempt]);
  const fullName = identity ? [identity.user.first_name, identity.user.last_name].filter(Boolean).join(' ') : '';
  const pageTitle = mode === 'teacher' ? 'O‘qituvchi kabineti' : studentPages.find(item => item.id === page)!.label;
  const studentNav = (mobile = false) => <nav className={mobile ? 'student-bottom-nav' : 'workspace-nav'} aria-label={mobile ? 'O‘quvchi menyusi' : 'Asosiy bo‘limlar'}>{studentPages.map(item => <button key={item.id} disabled={switching} className={mode === 'student' && page === item.id ? 'nav-active' : ''} aria-current={mode === 'student' && page === item.id ? 'page' : undefined} onClick={() => void navigate('student', item.id)}><Icon name={item.icon} /><span>{item.label}</span></button>)}</nav>;
  return <div className={'app-shell refined-ui mode-' + mode + (focused ? ' focus-mode' : '') + (identity && mode === 'student' && !focused ? ' has-bottom-nav' : '')}>
    <a className="skip-link" href="#content">Asosiy mazmunga o‘tish</a>
    <aside className="sidebar"><Brand /><div className="sidebar-label">BILIM SARI BIRGA</div>{studentNav()}
      <div className="sidebar-bottom">{identity?.can_teach && <button className={'teacher-entry ' + (mode === 'teacher' ? 'nav-active' : '')} disabled={switching} onClick={() => void navigate('teacher')}><Icon name="grid" /><span>O‘qituvchi kabineti</span><Icon name="chevron" size={16} /></button>}<button className="help-link" onClick={() => setGuide(true)}><Icon name="help" />Qanday foydalaniladi?</button><span className="sidebar-copyright">Basirat · Barcha uchun ochiq</span></div></aside>
    <div className="workspace"><header className="app-header"><div className="mobile-brand"><Brand /></div><span className="desktop-breadcrumb">Basirat<Icon name="chevron" size={14} /><strong>{pageTitle}</strong></span><div className="header-actions">{identity && <details className="account-menu" ref={accountMenu}><summary aria-label="Hisob menyusi"><span className="avatar">{identity.user.first_name.slice(0, 1).toUpperCase()}</span><span className="account-name">{identity.user.first_name}</span><Icon name="chevron" size={15} /></summary><div className="account-dropdown"><strong>{fullName}</strong><button disabled={switching} onClick={() => void navigate('student', 'profile')}><Icon name="users" size={18} />Profil</button>{identity.can_teach && <button disabled={switching} onClick={() => void navigate(mode === 'teacher' ? 'student' : 'teacher', 'tests')}><Icon name={mode === 'teacher' ? 'book' : 'grid'} size={18} />{mode === 'teacher' ? 'Testlarga qaytish' : 'O‘qituvchi kabineti'}</button>}<button onClick={() => { if (accountMenu.current) accountMenu.current.open = false; setGuide(true); }}><Icon name="help" size={18} />Yordam</button></div></details>}</div></header>
      <main id="content" className={'content-main' + (identity && mode === 'student' && page === 'tests' && !focused ? ' catalog-main' : '')}>
        {navigationError && <Alert>{navigationError}</Alert>}
        {!identity ? <section className="card auth-card">{browserLogin ? <BrowserLogin completed={setIdentity} /> : error ? <><span className="empty-icon"><Icon name="send" size={30} /></span><span className="eyebrow">BASIRAT TESTLAR</span><h1>Hisobga kirish</h1><p>Telegram botidagi <strong>Testlar</strong> tugmasi orqali kiring.</p><Alert>{error}</Alert><button onClick={() => setLoginAttempt(i => i + 1)}><Icon name="refresh" size={18} />Qayta ulanish</button><button className="quiet" onClick={() => setGuide(true)}>Qanday foydalaniladi?</button></> : <><Loading label="Hisob tekshirilmoqda…" /></>}</section> : mode === 'teacher' && identity.can_teach ? <>
          {!identity.profile && <PublisherProfile prompt profile={identity.profile} suggestedName={fullName} saved={profile => setIdentity({ ...identity, profile })} />}
          <Teacher botImportUrl={identity.bot_import_url} initialImport={entryImport.current} backToStudent={() => void navigate('student', 'tests')} />
        </> : page === 'profile' ? <div className="profile-page">
          <PageHeading icon="users" title="Profil" />
          <section className="card student-profile"><span className="avatar">{identity.user.first_name.slice(0, 1).toUpperCase()}</span><div><h2>{fullName}</h2><p><Icon name="shield" size={14} />Telegram hisobi</p></div></section>
          {identity.can_teach && <button className="profile-teacher-link" onClick={() => void navigate('teacher')}><span className="heading-symbol"><Icon name="grid" size={20} /></span><span><strong>O‘qituvchi kabineti</strong><small>Test yuklash va natijalar</small></span><Icon name="arrow" size={18} /></button>}
          <PublisherProfile profile={identity.profile} suggestedName={fullName} saved={profile => setIdentity({ ...identity, profile })} />
          <button className="secondary" onClick={() => setGuide(true)}><Icon name="help" size={18} />Yordam</button>
          {(identity.show_payments || (identity.session_audience === 'browser' && identity.show_web_payments)) && <details className="card account-payments"><summary><span><Icon name="spark" size={18} />Sinov to‘lovlari</span><span className="muted">Admin</span><Icon name="chevron" size={16} /></summary>{identity.show_payments && <PaymentPanel />}{identity.session_audience === 'browser' && identity.show_web_payments && <BrowserPaymentPanel />}</details>}
        </div> : <StudentCatalog firstName={identity.user.first_name} section={page} initialHandle={entryTest.current} onFocus={focusStudent} renderAttempt={(test, back, done) => <ProtectedTest><Attempt key={test.id} initial={test} back={back} done={done} /></ProtectedTest>} />}
      </main><footer className="workspace-footer"><span>Basirat · Barcha uchun ochiq</span><button className="quiet" onClick={() => setGuide(true)}>Yordam<Icon name="help" size={15} /></button></footer>
    </div>{identity && mode === 'student' && !focused && studentNav(true)}<Guide open={guide} close={() => setGuide(false)} />
  </div>;
}

function Teacher({ botImportUrl, initialImport, backToStudent }: { botImportUrl?: string | null; initialImport: string | null; backToStudent(): void }) {
  const [imports, setImports] = useState<ImportRecord[]>([]);
  const [tests, setTests] = useState<TestSummary[]>([]);
  const [counts, setCounts] = useState<TeacherCounts | null>(null);
  const [nextCursor, setNextCursor] = useState<number | null>(null);
  const [moreBusy, setMoreBusy] = useState(false);
  const loadedPages = useRef(1);
  const listGeneration = useRef(0);
  const [selectedImport, setSelectedImport] = useState<string | null>(initialImport);
  const [selectedTest, setSelectedTest] = useState<number | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [list, setList] = useState<'tests' | 'imports' | 'results'>('tests');
  const [search, setSearch] = useState('');
  const [loaded, setLoaded] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  useEffect(() => { window.scrollTo({ top: 0 }); }, [selectedImport, selectedTest]);
  async function refresh() {
    const generation = ++listGeneration.current;
    try {
      const a = await api<ImportRecord[]>('/teacher/imports');
      const collected: TestSummary[] = [];
      let cursor: number | null = null;
      let totals: TeacherCounts | null = null;
      for (let index = 0; index < loadedPages.current; index++) {
        const params = new URLSearchParams({ q: search });
        if (cursor) params.set('before', String(cursor));
        const page: CatalogPage = await api<CatalogPage>('/teacher/tests?' + params);
        collected.push(...page.items); cursor = page.next_cursor; totals = page.counts || null;
        if (!cursor) break;
      }
      if (generation !== listGeneration.current) return false;
      setImports(a.filter(item => item.status !== 'published')); setTests(collected); setCounts(totals); setNextCursor(cursor); setLoaded(true); setError(''); return true;
    } catch (error) { if (generation === listGeneration.current) setError(message(error)); return false; }
  }
  useEffect(() => { loadedPages.current = 1; setTests([]); setLoaded(false); void refresh(); const timer = setInterval(() => void refresh(), 5000); return () => { clearInterval(timer); ++listGeneration.current; }; }, [search]);
  async function upload() {
    setBusy(true); setError('');
    try {
      const data = new FormData(); files.forEach(file => data.append('files', file));
      const created = await api<{ id: string }>('/teacher/imports', { method: 'POST', body: data });
      setFiles([]); setUploadOpen(false); setSelectedImport(created.id); await refresh();
    } catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  const filteredTests = tests.filter(test => `${test.title} ${test.publisher_name} ${test.subject}`.toLocaleLowerCase().includes(search.toLocaleLowerCase()));
  const filteredImports = imports.filter(item => item.title.toLocaleLowerCase().includes(search.toLocaleLowerCase()));
  const testPage = usePagedList(filteredTests, 3, list + search);
  const importPage = usePagedList(filteredImports, 3, list + search);
  const listing = list === 'imports' ? importPage : testPage;
  async function changeListPage(index: number) {
    if (index < listing.pages) { listing.setPage(index); return; }
    if (!nextCursor || list === 'imports' || moreBusy) return;
    setMoreBusy(true); loadedPages.current++;
    try { if (await refresh()) testPage.setPage(index); else loadedPages.current--; }
    finally { setMoreBusy(false); }
  }
  if (selectedImport) return <ImportEditor id={selectedImport} back={() => { setSelectedImport(null); void refresh(); }} published={id => { setSelectedImport(null); setSelectedTest(id); void refresh(); }} />;
  if (selectedTest) return <TeacherResults key={selectedTest} id={selectedTest} back={() => { setSelectedTest(null); void refresh(); }} newSession={id => { setList('tests'); setSelectedTest(id); void refresh(); }} />;
  function goToUpload() { setUploadOpen(true); requestAnimationFrame(() => window.document.getElementById('upload-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' })); }
  return <div className="teacher-home">
    <button className="back-link teacher-return" onClick={backToStudent}><Icon name="back" size={17} />Testlarga qaytish</button>
    <PageHeading icon="grid" title="O‘qituvchi kabineti" action={<button onClick={goToUpload}><Icon name="plus" size={18} />Test yuklash</button>} />
    <div className="teacher-summary"><span><strong>{loaded ? counts?.total ?? tests.length : '—'}</strong> sessiya</span><span><i className="result-dot correct" /><strong>{loaded ? counts?.active ?? tests.filter(t => t.status === 'active').length : '—'}</strong> faol</span><button className="quiet" onClick={() => setList('imports')}><Icon name="edit" size={16} /><strong>{loaded ? counts?.review ?? imports.filter(i => i.status === 'review').length : '—'}</strong> tekshirishga tayyor<Icon name="chevron" size={14} /></button></div>
    {uploadOpen && <section className="teacher-upload" id="upload-panel" aria-label="Test yuklash"><div className="section-heading"><div><h2>Test yuklash</h2></div><button className="icon-button" aria-label="Yuklash oynasini yopish" disabled={busy} onClick={() => setUploadOpen(false)}><Icon name="close" /></button></div><p>AI ajratgan savol va javoblarni nashrdan oldin tekshirasiz.</p><div className="telegram-upload"><div><h3>Telegramdan</h3><p>PDF yoki rasmlarni botga yuboring.</p></div><button className="secondary" onClick={() => {
      const telegram = window.Telegram?.WebApp;
      if (botImportUrl) {
        if (telegram?.openTelegramLink) telegram.openTelegramLink(botImportUrl);
        else { location.assign(botImportUrl); return; }
      }
      telegram?.close();
    }}><Icon name="send" size={18} />Botga yuborish</button></div>
    <section className="card local-upload" id="local-upload"><h3><Icon name="upload" size={18} />Qurilmadan tanlash</h3><div className="file-picker-grid"><label className="file-picker"><Icon name="file" size={26} /><strong>PDF hujjat</strong><span>Bitta hujjat</span><input aria-label="PDF hujjat" type="file" accept=".pdf,application/pdf" disabled={busy} onChange={e => { setFiles(Array.from(e.target.files || [])); e.target.value = ''; }} /></label><label className="file-picker"><Icon name="image" size={26} /><strong>Sahifa rasmlari</strong><span>JPG, PNG yoki WebP</span><input aria-label="Sahifa rasmlari" type="file" accept="image/*" multiple disabled={busy} onChange={e => { setFiles(Array.from(e.target.files || [])); e.target.value = ''; }} /></label></div>
      {!!files.length && <ol className="file-list">{files.map((file, i) => <li key={i}><span className="file-order">{i + 1}</span><span>{file.name}<small>{(file.size / 1024 / 1024).toFixed(1)} MB</small></span>{i > 0 && <button className="icon-button" aria-label={`${file.name} faylini oldinga ko‘chirish`} onClick={() => setFiles(list => { const next = [...list]; [next[i - 1], next[i]] = [next[i], next[i - 1]]; return next; })}>↑</button>}<button className="icon-button" aria-label={`${file.name} faylini olib tashlash`} onClick={() => setFiles(list => list.filter((_, n) => n !== i))}><Icon name="close" size={17} /></button></li>)}</ol>}
      <div className="upload-bottom"><span className="muted">Jami 20 MB gacha · Ko‘pi bilan 30 sahifa</span><button disabled={!files.length || busy} onClick={() => void upload()}>{busy ? <><span className="spinner" />Yuklanmoqda…</> : <><Icon name="spark" size={17} />Savollarni ajratish</>}</button></div></section>
    </section>}
    {error && <Alert>{error}</Alert>}
    <section className="card library teacher-library"><div className="library-header"><nav className="tabs" aria-label="Testlar ro‘yxati"><button className={list === 'tests' ? 'selected' : ''} aria-pressed={list === 'tests'} onClick={() => setList('tests')}>Testlar<span>{tests.length}</span></button><button className={list === 'imports' ? 'selected' : ''} aria-pressed={list === 'imports'} onClick={() => setList('imports')}>Qoralamalar<span>{imports.length}</span></button><button className={list === 'results' ? 'selected' : ''} aria-pressed={list === 'results'} onClick={() => setList('results')}>Natijalar</button></nav><label className="search-field"><Icon name="search" size={17} /><input aria-label="Testlarni qidirish" placeholder="Testni qidirish" value={search} onChange={e => setSearch(e.target.value)} /></label></div>
      {!loaded ? <Loading /> : list !== 'imports' ? !filteredTests.length ? <EmptyState title={search ? 'Test topilmadi' : 'Birinchi testingizni yarating'} action={!search && <button className="secondary" onClick={goToUpload}><Icon name="plus" size={17} />Test qo‘shish</button>}>{search ? 'Boshqa nom bilan qidirib ko‘ring.' : 'PDF yoki rasmlardan boshlang.'}</EmptyState> : <div className="test-list">{testPage.items.map(test => <button className="test-list-row" key={test.id} onClick={() => setSelectedTest(test.id)}><span className="list-icon"><Icon name={list === 'results' ? 'chart' : 'book'} /></span><span className="list-title"><strong>{test.title}</strong><span>{test.total_questions} savol · {visibilityLabel(test.visibility)} · {sessionDate(test.created_at)}</span></span><Badge status={test.status} /><Icon name="chevron" size={18} /></button>)}</div> : !filteredImports.length ? <EmptyState icon="file" title={search ? 'Qoralama topilmadi' : 'Hali qoralamalar yo‘q'}>{search ? 'Boshqa nom bilan qidirib ko‘ring.' : 'Yuklangan fayllar shu yerda ko‘rinadi.'}</EmptyState> : <div className="test-list">{importPage.items.map(item => <button className="test-list-row" key={item.id} onClick={() => setSelectedImport(item.id)}><span className="list-icon"><Icon name="file" /></span><span className="list-title"><strong>{item.title}</strong><span>{['processing', 'queued'].includes(item.status) ? `${item.progress}% tayyor` : item.document ? `${item.document.questions.length} ta savol` : 'PDF va rasmlardan test'}</span></span><Badge status={item.status} /><Icon name="chevron" size={18} /></button>)}</div>}
    </section>
    {loaded && <PageControls page={listing.page} pages={listing.pages} hasMore={list !== 'imports' && Boolean(nextCursor)} busy={moreBusy} onChange={index => void changeListPage(index)} label="O‘qituvchi testlari sahifalari" />}
  </div>;
}

function ImportEditor({ id, back, published }: { id: string; back(): void; published(id: number): void }) {
  const [voiceBusy, setVoiceBusy] = useState(false);
  const voiceActive = useRef(false);
  function voiceActivity(active: boolean) { voiceActive.current = active; setVoiceBusy(active); }
  function requireVoiceReady() {
    if (voiceActive.current) throw new Error('Avval ovozli izohni to‘xtatib yuklang yoki bekor qiling.');
  }
  const confirm = useConfirmation();
  const wideSource = useMediaQuery('(min-width: 1251px)');
  const [record, setRecord] = useState<ImportRecord | null>(null);
  const [document, setDocument] = useState<TestDocument | null>(null);
  const revision = useRef(0);
  const latestDocument = useRef<TestDocument | null>(null);
  const savedDocument = useRef('');
  const metadata = useRef<{ visibility: Visibility; subject: string; duration_minutes: number | null }>({ visibility: 'public', subject: '', duration_minutes: null });
  const saving = useRef<Promise<number> | null>(null);
  const conflict = useRef(false);
  const [dirty, setDirty] = useState(false);
  const [questionIndex, setQuestionIndex] = useState(0);
  const [tab, setTab] = useState<'questions' | 'passages'>('questions');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [keys, setKeys] = useState('');
  async function load() {
    try {
      const item = await api<ImportRecord>('/teacher/imports/' + id);
      setRecord(item);
      if (item.document && !latestDocument.current) {
        const prepared = prepareReview(item.document);
        setDocument(prepared); latestDocument.current = prepared; revision.current = item.revision;
        metadata.current = { visibility: item.visibility, subject: item.subject, duration_minutes: item.duration_minutes };
        savedDocument.current = JSON.stringify({ document: item.document, ...metadata.current });
        setDirty(JSON.stringify(prepared) !== JSON.stringify(item.document));
      }
    } catch (error) { setError(message(error)); }
  }
  useEffect(() => { void load(); }, [id]);
  useEffect(() => {
    if (record && ['collecting', 'queued', 'processing'].includes(record.status)) {
      const timer = setInterval(() => void load(), 3000); return () => clearInterval(timer);
    }
  }, [record?.status]);
  useEffect(() => {
    if (dirty) window.Telegram?.WebApp.enableClosingConfirmation();
    const warn = (event: BeforeUnloadEvent) => { if (dirty) { event.preventDefault(); event.returnValue = ''; } };
    window.addEventListener('beforeunload', warn);
    return () => { window.removeEventListener('beforeunload', warn); window.Telegram?.WebApp.disableClosingConfirmation(); };
  }, [dirty]);
  useEffect(() => {
    if (!dirty || busy) return;
    const timer = setTimeout(() => void save().catch(error => setError(message(error))), 1500);
    return () => clearTimeout(timer);
  }, [document, dirty, busy, record?.visibility, record?.subject, record?.duration_minutes]);
  function change(next: TestDocument) { const prepared = prepareReview(next); latestDocument.current = prepared; setDocument(prepared); setDirty(true); setNotice(''); }
  async function save() {
    while (saving.current) await saving.current;
    if (!latestDocument.current) return revision.current;
    if (conflict.current) throw new Error('Qoralama boshqa oynada o‘zgargan. O‘zgarishlaringizni nusxalab, qayta oching.');
    const serialized = JSON.stringify({ document: latestDocument.current, ...metadata.current });
    if (serialized === savedDocument.current) return revision.current;
    const task = (async () => {
      try {
        const result = await api<{ revision: number }>('/teacher/imports/' + id, { method: 'PUT', body: JSON.stringify({ ...JSON.parse(serialized), revision: revision.current }) });
        revision.current = result.revision; savedDocument.current = serialized;
        setDirty(JSON.stringify({ document: latestDocument.current, ...metadata.current }) !== serialized); setNotice('Qoralama saqlandi.');
        return result.revision;
      } catch (error) { if (error instanceof ApiError && error.status === 409) conflict.current = true; throw error; }
    })();
    saving.current = task;
    try { return await task; } finally { saving.current = null; }
  }
  useExitGuard(async () => { requireVoiceReady(); await save(); });
  async function act(publish = false) {
    if (voiceActive.current) return;
    setBusy(true); setError('');
    try {
      const current = await save();
      if (publish) {
        const result = await post<{ test_id: number }>('/teacher/imports/' + id + '/publish', { revision: current });
        published(result.test_id);
      }
    } catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  function updateQuestion(question: Question) {
    if (!document) return;
    change({ ...document, questions: document.questions.map((q, i) => i === questionIndex ? question : q) });
  }
  const reviewHeading = useRef<HTMLHeadingElement>(null);
  async function moveQuestion(next: number) {
    if (busy || voiceActive.current || next < 0 || next >= (latestDocument.current?.questions.length || 0)) return;
    setBusy(true); setError('');
    try {
      await save(); setQuestionIndex(next); setVisiblePage(0);
      requestAnimationFrame(() => { reviewHeading.current?.focus({ preventScroll: true }); reviewHeading.current?.scrollIntoView({ block: 'start' }); });
    } catch (error) { setError(message(error)); window.scrollTo({ top: 0 }); }
    finally { setBusy(false); }
  }
  const q = document?.questions[questionIndex];
  const sourcePage = q?.source_pages[0] || record?.assets.find(a => a.kind === 'page')?.page || 1;
  const [visiblePage, setVisiblePage] = useState(0);
  const pages = record?.assets.filter(a => a.kind === 'page') || [];
  const page = pages.find(a => a.page === (visiblePage || sourcePage));
  const reviewed = document?.questions.filter(q => q.reviewed).length || 0;
  const fullyReviewed = Boolean(document && document.questions.length >= 5 && reviewed === document.questions.length);
  async function leave() { setBusy(true); try { requireVoiceReady(); await save(); back(); } catch (error) { setError(message(error)); } finally { setBusy(false); } }
  useTelegramBack(() => { if (!busy) void leave(); });
  return <>
    <button className="back-link" disabled={busy || voiceBusy} onClick={() => void leave()}><Icon name="back" size={17} />O‘qituvchi kabineti</button>
    <PageHeading icon="edit" title="Testni tayyorlash" action={record && <Badge status={record.status} />} />
    <ol className="workflow-steps compact-workflow" aria-label="Test yaratish bosqichlari"><li className="done"><span><Icon name="check" size={14} /></span>Fayl yuklash</li><li className={document ? 'done' : 'current'}><span>{document ? <Icon name="check" size={14} /> : '2'}</span>AI ajratishi</li><li className={document ? 'current' : ''}><span>3</span>Tekshirish</li><li className={record?.status === 'published' ? 'done' : ''}><span>4</span>Nashr qilish</li></ol>
    {error && <Alert>{error}</Alert>}
    {notice && !dirty && <div className="save-notice" role="status"><Icon name="check" size={14} />{notice}</div>}
    {!record ? <Loading /> : record.status === 'published' ? <section className="card"><EmptyState icon="check" title="Testingiz tayyor!" action={<button onClick={() => published(record.published_test_id!)}>Test va natijalar<Icon name="arrow" size={17} /></button>}>Endi test havolasini o‘quvchilarga yuborishingiz mumkin.</EmptyState></section> : !document ? <section className="card processing-card"><span className="processing-icon"><Icon name={record.status === 'failed' ? 'refresh' : record.status === 'collecting' ? 'image' : 'spark'} size={32} /></span><Badge status={record.status} /><h2>{record.status === 'collecting' ? 'Rasmlar qabul qilinmoqda' : record.status === 'failed' ? 'Ajratish tugamadi' : 'Savollar ajratilmoqda'}</h2><p className="muted">{record.title}</p><div className="progress-label"><span>Tayyorlanish jarayoni</span><strong>{record.progress}%</strong></div><progress aria-label="Testni ajratish jarayoni" value={record.progress} max={100} />{record.status === 'collecting' ? <><p>{record.assets.filter(a => a.kind === 'source').length} ta rasm qabul qilindi. Qolgan sahifalarni botga yuboring, so‘ng ajratishni boshlang.</p><button disabled={busy} onClick={async () => { setBusy(true); setError(''); try { await post('/teacher/imports/' + id + '/start'); await load(); } catch (error) { setError(message(error)); } finally { setBusy(false); } }}><Icon name="spark" size={18} />Savollarni ajratish</button></> : <p>{record.error || 'Ilovani yopishingiz mumkin. Tayyor bo‘lgach, bot xabar beradi.'}</p>}{record.status === 'failed' && <button disabled={busy} onClick={async () => { setBusy(true); try { await post('/teacher/imports/' + id + '/retry'); await load(); } catch (error) { setError(message(error)); } finally { setBusy(false); } }}><Icon name="refresh" size={18} />Qayta urinish</button>}</section> : <fieldset className="editor-fields" disabled={busy}>
      <section className="card document-overview"><div className="overview-top"><span className="list-icon"><Icon name="file" size={23} /></span><div><Field label="Test nomi" rows={1} value={document.title} onChange={title => change({ ...document, title })} /></div></div>
        <details className="settings-disclosure"><summary><Icon name="edit" size={16} />Nashr sozlamalari<span>{visibilityLabel(record.visibility)} · {record.duration_minutes ? `${record.duration_minutes} daq.` : 'Cheklanmagan'}</span><Icon name="chevron" size={16} /></summary><PublicationFields visibility={record.visibility} subject={record.subject} duration={record.duration_minutes} change={(visibility, subject, duration_minutes) => { metadata.current = { visibility, subject, duration_minutes }; setRecord({ ...record, visibility, subject, duration_minutes }); setDirty(true); }} /></details>
        <div className="document-meta"><span><strong>{document.questions.length}</strong> ta savol</span><span><strong>{document.questions.filter(q => q.kind === 'open').length}</strong> ta ochiq javob</span><span className="reviewed-count"><Icon name="check" size={16} /><strong>{reviewed}/{document.questions.length}</strong> javob tayyor</span></div>
        {!!document.warnings.length && <details className="warning-details"><summary><Icon name="help" size={16} />E’tibor talab qiladi ({document.warnings.length})</summary><ul>{document.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul></details>}
        <details className="bulk-keys"><summary><Icon name="grid" size={16} />Javoblar kaliti<Icon name="plus" size={16} /></summary><p className="muted">Masalan: 1:A, 2:F, 3:B. To‘g‘ri kalitlar avtomatik saqlanadi.</p><Field label="Javoblar kaliti" placeholder="1:A, 2:F, 3:B" value={keys} onChange={setKeys} /><button className="secondary" onClick={() => {
          const pairs = Array.from(keys.matchAll(/(\d{1,2})\s*[.\-:)]\s*([A-F])/gi));
          if (!pairs.length) { setError('Kalitlar topilmadi. 1:A, 2:F formatidan foydalaning.'); return; }
          const mapping = Object.fromEntries(pairs.map(p => [Number(p[1]), p[2].toUpperCase()]));
          change({ ...document, questions: document.questions.map(q => q.kind !== 'open' && mapping[q.number] ? { ...q, answer: mapping[q.number], reviewed: false } : q) });
          setNotice('Kalitlar kiritildi. Tayyor javoblar avtomatik belgilanadi.');
        }}>Kalitlarni qo‘llash</button></details>
      </section>
      <nav className="tabs editor-tabs" aria-label="Tahrirlash bo‘limlari"><button className={tab === 'questions' ? 'selected' : ''} aria-pressed={tab === 'questions'} disabled={voiceBusy} onClick={() => setTab('questions')}><Icon name="grid" size={17} />Savollar<span>{document.questions.length}</span></button><button className={tab === 'passages' ? 'selected' : ''} aria-pressed={tab === 'passages'} disabled={voiceBusy} onClick={() => setTab('passages')}><Icon name="book" size={17} />Umumiy matnlar<span>{document.passages.length}</span></button></nav>
      <div className="editor-layout"><div className="editor-main">
        {tab === 'questions' ? <section className="card">
          <div className="section-heading"><h2 ref={reviewHeading} tabIndex={-1}>Savolni tahrirlash</h2><span className="muted">{questionIndex + 1} / {document.questions.length}</span></div><nav className="question-nav" aria-label="Tahrirlash uchun savolni tanlang">{document.questions.map((q, i) => <button key={i} disabled={busy || voiceBusy} aria-label={`${q.number}-savol${q.reviewed ? ', javob tayyor' : ', javob kerak'}`} aria-current={i === questionIndex ? 'step' : undefined} className={i === questionIndex ? 'selected' : q.reviewed ? 'complete' : 'secondary'} onClick={() => void moveQuestion(i)}>{q.number}</button>)}</nav>
          {q && <QuestionEditor key={questionIndex} question={q} passages={document.passages} pages={pages} update={updateQuestion} importId={id} voiceActivity={voiceActivity} />}
          <div className="actions editor-question-actions"><button className="secondary" disabled={voiceBusy || document.questions.length >= 44} onClick={() => { const number = Array.from({ length: 44 }, (_, i) => i + 1).find(n => !document.questions.some(q => q.number === n))!; change({ ...document, questions: [...document.questions, newQuestion(number)] }); setQuestionIndex(document.questions.length); }}><Icon name="plus" size={16} />Savol qo‘shish</button>{q && <button className="danger" disabled={voiceBusy} onClick={async () => { if (await confirm({ title: 'Savol o‘chirilsinmi?', description: `${q.number}-savol va uning javob mezoni qoralamadan olib tashlanadi.`, action: 'Savolni o‘chirish', danger: true })) { change({ ...document, questions: document.questions.filter((_, i) => i !== questionIndex) }); setQuestionIndex(0); } }}>O‘chirish</button>}</div>
        </section> : <section className="card">{document.passages.map((p, i) => <PassageEditor key={i} passage={p} pages={pages} update={next => change({ ...document, passages: document.passages.map((p, n) => i === n ? next : p), questions: document.questions.map(q => q.passage_id === p.id ? { ...q, reviewed: false } : q) })} remove={() => change({ ...document, passages: document.passages.filter((_, n) => n !== i) })} />)}<button onClick={() => change({ ...document, passages: [...document.passages, { id: 'p' + Date.now(), title: '', text: '', media: [], source_pages: [] }] })}>Matn qo‘shish</button></section>}
      </div><aside className="card source"><details open={wideSource}><summary><span><Icon name="file" size={18} />Asl hujjat</span><Icon name="chevron" size={17} /></summary><label className="field">Sahifani tanlang<select value={page?.page || ''} onChange={e => setVisiblePage(Number(e.target.value))}>{pages.map(p => <option key={p.id} value={p.page}>{p.page}-sahifa</option>)}</select></label>{page && <a className="source-image" href={assetUrl(page.id)} target="_blank" rel="noreferrer"><img src={assetUrl(page.id)} alt={`${page.page}-sahifa — kattalashtirish uchun bosing`} /><span><Icon name="search" size={16} />Kattalashtirish</span></a>}<p className="muted">Asldagi ataylab yozilgan imlo xatolarini saqlang.</p></details></aside></div>
      <footer className="sticky editor-footer review-footer">
        <div className="review-footer-status"><span className={'save-state ' + (dirty ? 'saving' : '')}><Icon name={dirty ? 'clock' : 'check'} size={15} />{busy ? 'Saqlanmoqda…' : dirty ? 'Avtomatik saqlanmoqda…' : 'Saqlangan'}</span><small>{fullyReviewed ? 'Nashrga tayyor' : `${reviewed}/${document.questions.length} javob tayyor`}</small></div>
        {tab === 'questions' && <nav className="review-traversal" aria-label="Savollarni ko‘rib chiqish"><button className="secondary" disabled={busy || voiceBusy || questionIndex === 0} onClick={() => void moveQuestion(questionIndex - 1)}><Icon name="back" size={16} />Oldingi</button><span>{questionIndex + 1}/{document.questions.length}</span><button disabled={busy || voiceBusy || questionIndex >= document.questions.length - 1} onClick={() => void moveQuestion(questionIndex + 1)}>Keyingi<Icon name="arrow" size={16} /></button></nav>}
        <div className="actions"><button className="secondary" disabled={busy || voiceBusy} onClick={() => void act()}>Saqlash</button><button className="success-action" disabled={busy || voiceBusy || !fullyReviewed} onClick={async () => { if (await confirm({ title: 'Test nashr qilinsinmi?', description: (record.visibility === 'public' ? 'Test katalogda ko‘rinadi. ' : 'Test faqat havola orqali ochiladi. ') + 'Nashr qilingach, savollar va javob mezonlari o‘zgarmaydi.', action: 'Nashr qilish' })) void act(true); }}><Icon name="send" size={17} />Nashr qilish</button></div>
      </footer>
    </fieldset>}
  </>;
}

function newQuestion(number: number): Question {
  return { number, kind: 'choice', text: '', options: [{ label: 'A', text: '' }, { label: 'B', text: '' }], passage_id: null, parts: [], source_pages: [], media: [], answer: '', rubric: '', accepted_answers: [], points: 2.5, reviewed: false, warnings: [] };
}

type PageAsset = { id: string; page: number };
function RegionEditor({ regions, pages, update }: { regions: Region[]; pages: PageAsset[]; update(regions: Region[]): void }) {
  const [pageNumber, setPageNumber] = useState(regions[0]?.page || pages[0]?.page || 1);
  const [start, setStart] = useState<{ x: number; y: number } | null>(null);
  const [end, setEnd] = useState<{ x: number; y: number } | null>(null);
  const page = pages.find(p => p.page === pageNumber);
  function position(event: React.PointerEvent<HTMLDivElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    return { x: Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)), y: Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)) };
  }
  return <details><summary>Diagramma va rasm sohalari ({regions.length})</summary>
    <p className="muted">Sahifani tanlang va kerakli diagramma ustida to‘rtburchak chizing. Boshqa savol va javoblar sohaga tushmasin.</p>
    <label className="field">Rasm joylashgan sahifa<select value={pageNumber} onChange={e => setPageNumber(Number(e.target.value))}>{pages.map(p => <option key={p.id} value={p.page}>{p.page}-sahifa</option>)}</select></label>
    {page && <div className="crop-canvas" onPointerDown={event => { event.currentTarget.setPointerCapture(event.pointerId); setStart(position(event)); setEnd(position(event)); }} onPointerMove={event => { if (start) setEnd(position(event)); }} onPointerCancel={() => { setStart(null); setEnd(null); }} onPointerUp={event => {
      if (!start) return; const end = position(event); const width = Math.abs(end.x - start.x), height = Math.abs(end.y - start.y);
      if (width > .01 && height > .01) update([...regions, { page: pageNumber, x: Math.min(start.x, end.x), y: Math.min(start.y, end.y), width, height, asset_id: '' }]);
      setStart(null); setEnd(null);
    }}><img src={assetUrl(page.id)} alt="Rasm sohasini belgilang yoki quyidagi maydonlar orqali joylashuvni sozlang" draggable={false} />{regions.filter(r => r.page === pageNumber).map((r, i) => <div key={i} className="crop-box" style={{ left: `${r.x * 100}%`, top: `${r.y * 100}%`, width: `${r.width * 100}%`, height: `${r.height * 100}%` }} />)}{start && end && <div className="crop-box crop-preview" style={{ left: `${Math.min(start.x, end.x) * 100}%`, top: `${Math.min(start.y, end.y) * 100}%`, width: `${Math.abs(start.x - end.x) * 100}%`, height: `${Math.abs(start.y - end.y) * 100}%` }} />}</div>}
    <button className="secondary" disabled={!page} onClick={() => update([...regions, { page: pageNumber, x: .1, y: .1, width: .3, height: .2, asset_id: '' }])}><Icon name="plus" size={15} />Soha qo‘shish</button>
    {regions.map((r, i) => <div className="region-row" key={i}><span>{i + 1}-rasm · {r.page}-sahifa</span>{(['x', 'y', 'width', 'height'] as const).map(key => <label key={key}>{{ x: 'Chapdan %', y: 'Tepadan %', width: 'Eni %', height: 'Bo‘yi %' }[key]}<input type="number" min="0" max="100" step="1" value={Number((r[key] * 100).toFixed(1))} onChange={e => update(regions.map((region, n) => n === i ? { ...region, [key]: Number(e.target.value) / 100, asset_id: '' } : region))} /></label>)}<button className="icon-button" aria-label={`${i + 1}-rasm sohasini o‘chirish`} onClick={() => update(regions.filter((_, n) => n !== i))}><Icon name="close" size={16} /></button></div>)}
  </details>;
}

function QuestionEditor({ question: q, passages, pages, update, importId, voiceActivity }: { question: Question; passages: Passage[]; pages: PageAsset[]; update(q: Question): void; importId: string; voiceActivity(active: boolean): void }) {
  const patch = (value: Partial<Question>) => update({ ...q, ...value, reviewed: false });
  const issues = questionIssues(q, passages.map(passage => passage.id));
  const [editing, setEditing] = useState(() => q.kind === 'open' || !q.text.trim() || q.options.length < 2);
  const passage = passages.find(item => item.id === q.passage_id);
  return <>
    {!!q.warnings.length && <Alert tone="warning">{q.warnings.join('\n')}</Alert>}
    {!editing && <section className="question-review-preview" aria-label={`${q.number}-savol ko‘rinishi`}>
      {passage && <details className="review-passage"><summary><Icon name="book" size={16} />{passage.title || 'Umumiy matn'}</summary><RichText text={passage.text} /></details>}
      <div className="review-question-text"><RichText text={q.text} /></div>
      <ol className="review-options">{q.options.map(option => <li key={option.label} className={q.answer === option.label ? 'key-selected' : ''}><b>{option.label}</b><RichText text={option.text} /></li>)}</ol>
    </section>}
    <details className="question-edit-details" open={editing} onToggle={event => setEditing(event.currentTarget.open)}><summary><Icon name="edit" size={16} />{q.kind === 'open' ? 'Javob va tekshirish mezoni' : 'Matn va variantlarni tahrirlash'}<Icon name="chevron" size={16} /></summary>
    <details className="settings-disclosure question-settings"><summary><Icon name="edit" size={16} />Savol sozlamalari<span>{q.kind === 'open' ? 'Ochiq javob' : q.kind === 'matching' ? 'Moslashtirish' : 'Variantli'}</span><Icon name="chevron" size={16} /></summary>
    <div className="row"><label>Savol raqami<input type="number" min="1" max="44" value={q.number} onChange={e => patch({ number: Number(e.target.value) })} /></label><label>Turi<select value={q.kind} onChange={e => { const kind = e.target.value as Question['kind']; patch({ kind, options: kind === 'open' ? [] : q.options.length ? q.options : [{ label: 'A', text: '' }, { label: 'B', text: '' }], parts: kind === 'open' ? q.parts : [], answer: '' }); }}><option value="choice">Variantli</option><option value="matching">Moslashtirish</option><option value="open">Ochiq</option></select></label></div>
    <label className="field">Umumiy matn<select value={q.passage_id || ''} onChange={e => patch({ passage_id: e.target.value || null })}><option value="">Alohida savol</option>{passages.map(p => <option key={p.id} value={p.id}>{p.title || p.id}</option>)}</select></label>
    </details>
    <Field label="Savol matni" rows={5} placeholder="Savolning to‘liq matnini kiriting…" value={q.text} onChange={text => patch({ text })} />
    <details className="format-help"><summary>Matn ko‘rinishi</summary><RichText text={q.text} /><p className="field-hint">**qalin**, *kursiv*, &lt;u&gt;tagiga chizish&lt;/u&gt;</p></details>

    {q.kind !== 'open' ? <>
      <h3 className="field-heading">Javob variantlari</h3>{q.options.map((option, index) => <div className="option-editor" key={index}><b>{option.label}</b><textarea aria-label={`${option.label} variant matni`} rows={2} value={option.text} onChange={e => patch({ options: q.options.map((o, i) => i === index ? { ...o, text: e.target.value } : o) })} /><button className="icon-button" aria-label={`${option.label} variantini o‘chirish`} onClick={() => patch({ options: q.options.filter((_, i) => i !== index) })}><Icon name="close" size={16} /></button></div>)}
      <button className="secondary" disabled={q.options.length >= 6} onClick={() => { const label = 'ABCDEF'.split('').find(label => !q.options.some(o => o.label === label))!; patch({ options: [...q.options, { label, text: '' }] }); }}>Variant qo‘shish</button>

    </> : <>
      {q.parts.map((part, index) => <div className="option-editor" key={part.id}><b>{part.id})</b><textarea aria-label={`${part.id} qism matni`} value={part.prompt} onChange={e => patch({ parts: q.parts.map((p, i) => i === index ? { ...p, prompt: e.target.value } : p) })} /><button className="icon-button" aria-label={`${part.id} qismini o‘chirish`} onClick={() => patch({ parts: q.parts.filter((_, i) => i !== index) })}><Icon name="close" size={16} /></button></div>)}
      <button className="secondary" disabled={q.parts.length >= 6} onClick={() => patch({ parts: [...q.parts, { id: 'abcdef'.split('').find(id => !q.parts.some(p => p.id === id))!, prompt: '' }] })}>a/b qism qo‘shish</button>
      <Field label="To‘g‘ri javob va tekshirish mezoni" rows={5} value={q.rubric} onChange={rubric => patch({ rubric })} />
      {!q.parts.length && <Field label="Aniq qabul qilinadigan javoblar · har biri yangi qatorda" value={q.accepted_answers.join('\n')} onChange={value => patch({ accepted_answers: value.split('\n') })} />}
      <label className="field">Savol uchun ball<input type="number" min="0.1" max="100" step="0.1" value={q.points} onChange={e => patch({ points: Number(e.target.value) })} /></label>
      {!!q.parts.length && <p className="muted">Barcha qismlar to‘g‘ri bo‘lsa, bu bitta savol uchun {q.points} ball beriladi.</p>}
    </>}
    <RegionEditor regions={q.media} pages={pages} update={media => patch({ media })} />
    </details>
    {q.kind !== 'open' && (<fieldset className="answer-key-picker"><legend>To‘g‘ri javob</legend><div>{q.options.map(option => <label key={option.label} className={q.answer === option.label ? 'chosen' : ''}><input type="radio" name="teacher-answer-key" value={option.label} checked={q.answer === option.label} onChange={() => patch({ answer: option.label })} /><span>{option.label}</span></label>)}</div></fieldset>)}
    <VoiceExplanation importId={importId} number={q.number} audio={q.explanation_audio} saved={explanation_audio => update({ ...q, explanation_audio })} activity={voiceActivity} />
    <div className={'question-readiness ' + (issues.length ? 'needs-answer' : 'answer-ready')} role="status"><Icon name={issues.length ? 'edit' : 'check'} size={17} /><span>{issues.length ? issues.join(' ') : 'Javob tayyor · avtomatik saqlanadi'}</span></div>
  </>;
}

function PassageEditor({ passage: p, pages, update, remove }: { passage: Passage; pages: PageAsset[]; update(p: Passage): void; remove(): void }) {
  const confirm = useConfirmation();
  return <article className="passage-editor"><p className="eyebrow">UMUMIY MATN · {p.id}</p><Field label="Matn sarlavhasi" value={p.title} rows={1} onChange={title => update({ ...p, title })} /><Field label="Umumiy matn, izohlar va lug‘at" value={p.text} rows={12} onChange={text => update({ ...p, text })} /><RegionEditor regions={p.media} pages={pages} update={media => update({ ...p, media })} /><button className="danger" onClick={async () => { if (await confirm({ title: 'Umumiy matn o‘chirilsinmi?', description: 'Matnga bog‘langan savollarni ham tekshirib chiqishingiz kerak bo‘ladi.', action: 'Matnni o‘chirish', danger: true })) remove(); }}>Matnni o‘chirish</button></article>;
}

function Attempt({ initial, back, done }: { initial: StudentTest; back(): void; done(): void }) {
  const [answers, setAnswers] = useState<Answers>(initial.draft);
  const [result, setResult] = useState<Submission | null>(initial.submission);
  const [celebrate, setCelebrate] = useState(false);
  const receivedSubmission = useRef(Boolean(initial.submission));
  const acceptSubmission = useCallback((submission: Submission) => {
    if (!receivedSubmission.current) setCelebrate(true);
    receivedSubmission.current = true;
    setResult(submission);
  }, []);
  const clock = useAttemptTimer(initial, result, acceptSubmission);
  useEffect(() => {
    if (!celebrate) return;
    const timer = window.setTimeout(() => setCelebrate(false), 3400);
    return () => window.clearTimeout(timer);
  }, [celebrate]);
  const confirm = useConfirmation();
  const [index, setIndex] = useState(0);
  const [review, setReview] = useState(false);
  const [error, setError] = useState('');
  const [saveState, setSaveState] = useState('Saqlangan');
  const [busy, setBusy] = useState(false);
  const revision = useRef(initial.revision);
  const [navOpen, setNavOpen] = useState(false);
  const wideMap = useMediaQuery('(min-width: 801px)');
  const questionHeading = useRef<HTMLHeadingElement>(null);
  const attemptMain = useRef<HTMLDivElement>(null);
  const latest = useRef(answers);
  const saved = useRef(JSON.stringify(initial.draft));
  const saving = useRef<Promise<void> | null>(null);
  const conflict = useRef(false);
  const questions = initial.document.questions;
  const q = questions[index];
  useEffect(() => { if (review || result) window.scrollTo({ top: 0 }); }, [review, Boolean(result)]);
  async function flush() {
    while (saving.current) await saving.current;
    const serialized = JSON.stringify(latest.current);
    if (result) return;
    if (clock.isExpired()) { await clock.sync(); return; }
    if (serialized === saved.current) return;
    if (conflict.current) throw new Error('Javoblar boshqa oynada o‘zgargan. Qayta ochishdan oldin javoblaringizni nusxalang.');
    const task = (async () => {
      setSaveState('Saqlanmoqda…');
      try {
        const value = await post<{ revision: number }>('/tests/' + initial.code + '/draft', { answers: JSON.parse(serialized), revision: revision.current });
        revision.current = value.revision; saved.current = serialized; setSaveState(JSON.stringify(latest.current) === serialized ? 'Saqlangan' : 'Saqlanmoqda…');
      } catch (error) {
        if (error instanceof ApiError && error.status === 409 && initial.timer) {
          const status = await clock.sync();
          if (status?.submission) { setSaveState('Topshirilgan'); return; }
        }
        if (error instanceof ApiError && error.status === 409) conflict.current = true;
        setSaveState('Saqlanmadi · qayta uriniladi'); throw error;
      }
    })();
    saving.current = task;
    try { await task; } finally { saving.current = null; }
  }
  useExitGuard(flush);
  async function leaveAttempt() {
    if (result) { done(); return; }
    if (initial.timer && !clock.isExpired() && !await confirm({ title: 'Vaqt davom etadi', description: 'Testdan chiqsangiz ham vaqt to‘xtamaydi. Faqat qolgan vaqt ichida qaytishingiz mumkin. Vaqt tugaganda serverda saqlangan javoblaringiz avtomatik topshiriladi.', action: 'Testdan chiqish' })) return;
    try { await flush(); done(); } catch (error) { setError(message(error)); }
  }
  useTelegramBack(() => { if (busy) return; if (review && !result) { setReview(false); return; } void leaveAttempt(); });
  useEffect(() => {
    const timer = setInterval(() => { if (!result) void flush().catch(error => setError(message(error))); }, 1500);
    return () => clearInterval(timer);
  }, [result]);
  useEffect(() => {
    if (result) return;
    window.Telegram?.WebApp.enableClosingConfirmation();
    const warn = (event: BeforeUnloadEvent) => { if (JSON.stringify(latest.current) !== saved.current) { event.preventDefault(); event.returnValue = ''; } };
    window.addEventListener('beforeunload', warn);
    return () => { window.removeEventListener('beforeunload', warn); window.Telegram?.WebApp.disableClosingConfirmation(); };
  }, [result]);
  useEffect(() => {
    if (!result) return;
    const timer = setInterval(() => { void api<Submission>('/tests/' + initial.code + '/result').then(setResult).catch(error => setError(message(error))); }, 5000);
    return () => clearInterval(timer);
  }, [Boolean(result)]);
  function change(value: string | Record<string, string>) {
    if (busy || result || clock.isExpired()) return;
    const next = { ...latest.current, [q.number]: value }; latest.current = next; setAnswers(next); setSaveState('Saqlanmoqda…'); setError('');
  }
  async function submit() {
    setBusy(true); setError('');
    try { await flush(); const submission = await post<Submission>('/tests/' + initial.code + '/submit', { answers: latest.current }); acceptSubmission(submission); }
    catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  const count = questions.filter(q => questionAnswered(q.parts, answers[q.number])).length;
  const passage = initial.document.passages.find(p => p.id === q?.passage_id);
  const currentAnswer = answers[q?.number];
  const currentParts = typeof currentAnswer === 'object' ? currentAnswer : {};
  function goTo(next: number) {
    const passageChanged = questions[next]?.passage_id && questions[next].passage_id !== q?.passage_id;
    setIndex(next); setReview(false); if (!wideMap) setNavOpen(false);
    requestAnimationFrame(() => {
      questionHeading.current?.focus({ preventScroll: true });
      (passageChanged ? attemptMain.current : questionHeading.current)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }
  function answerPreview(value: string | Record<string, string> | undefined, parts: { id: string }[]) {
    if (parts.length) return parts.map(part => `${part.id}) ${typeof value === 'object' && value[part.id]?.trim() ? value[part.id] : 'Javob yo‘q'}`).join('\n');
    return typeof value === 'string' && value.trim() ? value : 'Javob yo‘q';
  }
  return <>
    <button className="back-link" disabled={busy} onClick={() => void leaveAttempt()}><Icon name="back" size={17} />{result ? 'Ro‘yxatga qaytish' : initial.timer ? 'Testdan chiqish' : 'Saqlab chiqish'}</button>
    <section className="attempt-heading"><div><div className="actions"><strong>{initial.publisher_name}</strong><span className="muted">{questions.length} ta savol</span></div><h1>{initial.document.title}</h1></div>{!result && <span className={'save-state ' + (saveState !== 'Saqlangan' ? 'saving' : '')} role="status"><Icon name={saveState === 'Saqlangan' ? 'check' : 'clock'} size={15} />{saveState}</span>}</section>
    {!result && !initial.timer && <p className="field-hint">Vaqt cheklanmagan. Saqlab chiqib, testni keyinroq davom ettirishingiz mumkin.</p>}
    {!result && clock.seconds !== null && <div className={'attempt-timer ' + (clock.expired ? 'timer-expired' : clock.seconds <= 60 ? 'timer-urgent' : '')}><Icon name="clock" size={22} /><div><strong>{clock.expired ? 'Vaqt tugadi' : 'Qolgan vaqt'}</strong><span>{clock.expired ? 'Saqlangan javoblar topshirilmoqda…' : 'Ilovani yopish vaqtni to‘xtatmaydi'}</span></div><output role="timer" aria-live="off" aria-label="Qolgan vaqt">{formatCountdown(clock.seconds)}</output></div>}
    {!result && clock.seconds !== null && clock.seconds > 0 && clock.seconds <= 60 && <p className="timer-warning" role="alert">Bir daqiqa yoki undan kam vaqt qoldi. Javoblaringiz saqlanganini tekshiring.</p>}
    {!result && clock.problem && <Alert tone="warning">{clock.problem}<button className="quiet" onClick={() => void clock.sync().catch(() => {})}>Qayta ulanish</button></Alert>}
    {error && !result && <Alert>{error}</Alert>}
    {result ? <StudentResult result={result} back={done} celebrate={celebrate} /> : initial.status !== 'active' ? <section className="card"><EmptyState icon="clock" title="Test yakunlangan" action={<button className="secondary" onClick={back}>Boshqa testga kirish</button>}>Bu testga yangi javoblar qabul qilinmaydi.</EmptyState></section> : review ? <>
      <section className="card review-summary"><h2>Topshirishga tayyormisiz?</h2><p>Topshirgach javoblar o‘zgarmaydi.</p><div className="review-counts"><span><strong>{count}</strong> javob berilgan</span><span className={count < questions.length ? 'unanswered-count' : ''}><strong>{questions.length - count}</strong> to‘liq javobsiz</span></div>{count < questions.length && <Alert tone="warning">{questions.length - count} ta savol to‘liq javobsiz. Bo‘sh yoki to‘liq bo‘lmagan javoblar noto‘g‘ri hisoblanadi.</Alert>}</section>
      <section className="card review-list"><div className="section-heading"><h2>Javoblaringiz</h2><span className="muted">{questions.length} ta savol</span></div>{questions.map((q, i) => <button className="review-row" disabled={busy} key={q.number} onClick={() => goTo(i)}><span className={'review-number ' + (questionAnswered(q.parts, answers[q.number]) ? 'answered' : '')}>{q.number}</span><span><strong>{q.number}-savol</strong><span className="answer-preview">{answerPreview(answers[q.number], q.parts)}</span></span><Icon name="edit" size={17} /></button>)}</section><footer className="sticky attempt-footer"><button className="secondary" disabled={busy} onClick={() => setReview(false)}><Icon name="back" size={17} />Savollarga qaytish</button><button className="submit-test" disabled={busy || clock.expired} onClick={() => void submit()}>{busy ? <><span className="spinner" />Topshirilmoqda…</> : <>Tasdiqlash va topshirish<Icon name="send" size={17} /></>}</button></footer>
    </> : q && <>
      <div className="attempt-progress"><div className="progress-label"><span><strong>{count}</strong> / {questions.length} javob berilgan</span><button className="quiet" onClick={() => setReview(true)}>Javoblarim<Icon name="arrow" size={15} /></button></div><progress aria-label="Javob berilgan savollar" value={count} max={questions.length} /></div>
      <div className="attempt-layout"><aside className={'card question-map ' + (navOpen ? 'map-open' : '')}><button className="map-toggle" onClick={() => setNavOpen(value => !value)} aria-expanded={navOpen || wideMap} aria-controls="question-map"><span><Icon name="grid" size={18} />Savollar</span><span>{index + 1}/{questions.length}<Icon name="chevron" size={16} /></span></button><div className="map-content" id="question-map"><nav className="question-nav" aria-label="Savollar orasida o‘tish">{questions.map((question, i) => <button key={question.number} aria-current={i === index ? 'step' : undefined} aria-label={`${question.number}-savol${questionAnswered(question.parts, answers[question.number]) ? ', javob berilgan' : ', javobsiz'}`} className={i === index ? 'selected' : questionAnswered(question.parts, answers[question.number]) ? 'complete' : 'secondary'} onClick={() => goTo(i)}>{question.number}</button>)}</nav><div className="map-legend"><span><i className="legend-current" />Hozirgi savol</span><span><i className="legend-answered" />Javob berilgan</span><span><i />Javobsiz</span></div><p className="map-note"><Icon name="shield" size={17} />Topshirmaguningizcha javoblarni o‘zgartira olasiz.</p></div></aside><div ref={attemptMain} className="attempt-main">
      {passage && <details className="card passage" open><summary><span><Icon name="book" size={18} />{passage.title || 'Savol uchun umumiy matn'}</span><Icon name="chevron" size={17} /></summary><div className="passage-content"><RichText text={passage.text} />{passage.media.map(id => <img className="question-image" key={id} src={assetUrl(id)} alt="Matnga tegishli rasm" />)}</div></details>}
      <section className="card question-card"><div className="section-heading"><span className="eyebrow">{String(q.number).padStart(2, '0')}-SAVOL</span><span className="question-kind">{q.kind === 'open' ? 'Ochiq javob' : q.kind === 'matching' ? 'Moslashtirish' : 'Variantli savol'}</span></div><h2 ref={questionHeading} tabIndex={-1} className="question-text"><RichText text={q.text} /></h2>{q.media.map(id => <img className="question-image" key={id} src={assetUrl(id)} alt="Savol diagrammasi" />)}
        <fieldset className="editor-fields" disabled={busy || clock.expired}>{q.kind !== 'open' ? <fieldset className="choices"><legend>Bitta javobni tanlang</legend>{q.options.map(option => <label className={answers[q.number] === option.label ? 'chosen' : ''} key={option.label}><input type="radio" name={'q' + q.number} checked={answers[q.number] === option.label} onChange={() => change(option.label)} /><span className="choice-letter">{option.label}</span><RichText text={option.text} /><span className="choice-indicator"><Icon name="check" size={13} /></span></label>)}<button className="quiet clear-choice" disabled={!answers[q.number]} onClick={() => change('')}>Tanlovni tozalash</button></fieldset> : <div className="open-answer">{q.parts.length ? <><p className="muted">Har bir qismga alohida javob yozing.</p>{q.parts.map(part => <Field key={part.id} label={`${part.id}) ${part.prompt}`} placeholder="Javobingizni shu yerga yozing…" value={currentParts[part.id] || ''} onChange={value => change({ ...currentParts, [part.id]: value })} />)}</> : <Field label="Javobingiz" placeholder="Fikringizni aniq va to‘liq yozing…" rows={6} value={typeof currentAnswer === 'string' ? currentAnswer : ''} onChange={change} />}<span className="answer-hint"><Icon name="edit" size={14} />Javobingiz avtomatik saqlanadi.</span></div>}</fieldset>
      </section></div></div><footer className="sticky attempt-footer"><button className="secondary" disabled={index === 0} onClick={() => goTo(index - 1)}><Icon name="back" size={17} /><span>Oldingi</span></button><span className="footer-position">{index + 1} / {questions.length}</span>{index < questions.length - 1 ? <button onClick={() => goTo(index + 1)}>Keyingi savol<Icon name="arrow" size={17} /></button> : <button onClick={() => setReview(true)}>Yakuniy tekshiruv<Icon name="check" size={17} /></button>}</footer>
    </>}
  </>;
}

function StudentResult({ result, back, celebrate = false }: { result: Submission; back(): void; celebrate?: boolean }) {
  const explanations = usePagedList(result.answers.filter(answer => answer.explanation_audio_url), 6, result.id);
  const correct = result.answers.filter(a => a.correct === true).length;
  const pending = result.answers.filter(a => a.correct === null).length;
  const wrong = result.answers.length - correct - pending;
  return <>
    {result.auto_submitted && <Alert tone="warning">Vaqt tugadi. Vaqt tugashidan oldin serverda saqlangan javoblaringiz avtomatik topshirildi.</Alert>}
    <section className={'card result-hero' + (celebrate ? ' submission-success' : '')}>{celebrate && <SubmissionCelebration />}<span className="result-check"><Icon name="check" size={30} /></span><span className="eyebrow">{result.score === undefined ? 'JAVOBLAR TOPSHIRILDI' : 'YAKUNIY NATIJA'}</span><h2>{celebrate ? 'Ajoyib! Test topshirildi.' : result.score === undefined ? 'Javoblaringiz qabul qilindi' : 'Yakuniy natija'}</h2><p>{result.score === undefined ? 'Javoblar holati quyida.' : 'Ball va o‘rningiz tayyor.'}</p>{result.score !== undefined && <div className="score-summary"><div><strong>{result.score}<small>ball</small></strong><span>To‘plangan ball</span></div><div><strong>{result.rank}<small>-o‘rin</small></strong><span>Reytingdagi o‘rningiz</span></div></div>}<div className="result-counts"><span><i className="result-dot correct" /><strong>{correct}</strong> to‘g‘ri</span><span><i className="result-dot incorrect" /><strong>{wrong}</strong> noto‘g‘ri</span>{pending > 0 && <span><i className="result-dot pending" /><strong>{pending}</strong> tekshirilmoqda</span>}</div></section>
    {result.score === undefined && <div className="result-waiting"><span className="stat-icon"><Icon name="clock" size={23} /></span><div><h3>{pending ? 'Ochiq javoblar tekshirilmoqda' : 'O‘qituvchi yakunlashi kutilmoqda'}</h3><p>Ball va o‘rin test yakunlangach ochiladi.</p></div></div>}
    <section className="card"><div className="section-heading"><h2>Javoblar holati</h2><span className="muted">{result.answers.length} ta savol</span></div><div className="result-grid">{result.answers.map(answer => <div className={'result-cell ' + (answer.correct === null ? 'pending' : answer.correct ? 'correct' : 'incorrect')} key={answer.number} aria-label={`${answer.number}-savol: ${answer.correct === null ? 'tekshirilmoqda' : answer.correct ? 'to‘g‘ri' : 'noto‘g‘ri'}`}><strong>{String(answer.number).padStart(2, '0')}</strong><Icon name={answer.correct === null ? 'clock' : answer.correct ? 'check' : 'close'} size={16} /></div>)}</div><div className="result-legend"><span><i className="result-dot correct" />To‘g‘ri</span><span><i className="result-dot incorrect" />Noto‘g‘ri</span><span><i className="result-dot pending" />Tekshirilmoqda</span></div></section>{!!explanations.items.length && <section className="card explanation-list"><div className="section-heading"><h2>O‘qituvchi izohlari</h2><Icon name="mic" size={20} /></div><p>Har bir savolning yechimini tinglang.</p>{explanations.items.map(answer => <details key={answer.number}><summary><Icon name="mic" size={17} />{answer.number}-savol izohi<Icon name="chevron" size={16} /></summary><ExplanationPlayer number={answer.number} url={answer.explanation_audio_url!} /></details>)}<PageControls page={explanations.page} pages={explanations.pages} onChange={explanations.setPage} label="Ovozli izohlar sahifalari" /></section>}<div className="result-back"><button className="secondary" onClick={back}><Icon name="back" size={17} />Ro‘yxatga qaytish</button></div>
  </>;
}

function TeacherResults({ id, back, newSession }: { id: number; back(): void; newSession(id: number): void }) {
  const confirm = useConfirmation();
  useTelegramBack(back);
  const [result, setResult] = useState<Results | null>(null);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [search, setSearch] = useState('');
  const [view, setView] = useState<'participants' | 'analysis'>('participants');
  const [sharing, setSharing] = useState(false);
  const [copied, setCopied] = useState(false);
  const sessionRequest = useRef(crypto.randomUUID().replaceAll('-', ''));
  const copyTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const answerDetail = useRef<HTMLElement>(null);
  const stackedResults = useMediaQuery('(max-width: 1250px)');
  useEffect(() => { if (selected && stackedResults) requestAnimationFrame(() => answerDetail.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })); }, [selected, stackedResults]);
  useEffect(() => () => clearTimeout(copyTimer.current), []);
  async function refresh() { try { setResult(await api<Results>(`/teacher/tests/${id}/results`)); } catch (error) { setError(message(error)); } }
  useEffect(() => { void refresh(); const timer = setInterval(() => void refresh(), 5000); return () => clearInterval(timer); }, [id]);
  async function action(path: string, data: unknown = {}) {
    setBusy(true); setError('');
    try { await post(`/teacher/tests/${id}/` + path, data); await refresh(); } catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  const pending = result?.answers.filter(a => a.grading_status !== 'done').length || 0;
  const participant = result?.submissions.find(s => s.id === selected);
  const participants = result?.submissions.filter(s => `${s.first_name} ${s.last_name || ''} ${s.user_id}`.toLocaleLowerCase().includes(search.toLocaleLowerCase())).sort((a, b) => result.test.status === 'finished' ? (a.rank || Infinity) - (b.rank || Infinity) : a.id - b.id) || [];
  const participantPage = usePagedList(participants, 4, search + id);
  const answerPage = usePagedList(result?.answers.filter(answer => answer.submission_id === selected) || [], 4, selected || 0);
  const analysisPage = usePagedList(result?.questions || [], 6, id);
  async function copyCode() {
    try { await navigator.clipboard.writeText(result!.test.share_url); setCopied(true); clearTimeout(copyTimer.current); copyTimer.current = setTimeout(() => setCopied(false), 2500); }
    catch { setError('Havolani nusxalash uchun quyidagi havola maydonidan foydalaning.'); }
  }
  return <><button className="back-link" onClick={back}><Icon name="back" size={17} />O‘qituvchi kabineti</button>{error && <Alert>{error}</Alert>}{result ? <>
    <PageHeading icon="chart" title={result.test.title} hint={result.test.publisher_name} action={<Badge status={result.test.status} />} />
    <div className="test-quick-actions"><button className="secondary" onClick={() => void copyCode()}><Icon name={copied ? 'check' : 'copy'} size={17} />{copied ? 'Nusxalandi' : 'Havola'}</button><a className="button" href={'https://t.me/share/url?' + new URLSearchParams({ url: result.test.share_url, text: result.test.title + ' · ' + result.test.publisher_name })} target="_blank" rel="noreferrer"><Icon name="send" size={17} />Ulashish</a>{result.test.status === 'finished' && <a className="button secondary" href={`/api/teacher/tests/${id}/report`}><Icon name="download" size={17} />Excel</a>}<button className="icon-button" title="Test sozlamalari" aria-label="Test sozlamalari" aria-expanded={sharing} onClick={() => setSharing(value => !value)}><Icon name="settings" size={18} /></button></div>
    {sharing && <details className="card share-panel" open={sharing} onToggle={event => setSharing(event.currentTarget.open)}><summary><span><Icon name="send" size={18} />Test sozlamalari</span><Icon name="chevron" size={18} /></summary><div className="share-content"><div className="section-heading"><div><h2>{result.test.publisher_name}</h2><p className="muted">{sessionDate(result.test.created_at)} · {result.test.id}-sessiya</p></div><span className="catalog-subject-tag">{visibilityLabel(result.test.visibility)}</span></div><label className="field">Test havolasi<input readOnly value={result.test.share_url} onFocus={event => event.target.select()} /></label><div className="actions"><button className="secondary" onClick={() => void copyCode()}><Icon name={copied ? 'check' : 'copy'} size={17} />{copied ? 'Nusxalandi' : 'Havolani nusxalash'}</button><a className="button" href={'https://t.me/share/url?' + new URLSearchParams({ url: result.test.share_url, text: result.test.title + ' · ' + result.test.publisher_name })} target="_blank" rel="noreferrer">Ulashish<Icon name="send" size={17} /></a></div>{result.test.template_id && <details className="session-settings"><summary>Ko‘rinish va vaqt<Icon name="edit" size={17} /></summary><ListingSettings test={result.test} saved={refresh} /><hr /><p>Yangi sessiyada qatnashchilar va ballar alohida hisoblanadi.</p><button className="secondary" disabled={busy} onClick={async () => {
        if (!await confirm({ title: 'Yangi sessiya ochilsinmi?', description: 'Shu savollar bilan yangi havola yaratiladi. Qatnashchilar va ballar alohida hisoblanadi.', action: 'Yangi sessiya ochish' })) return;
        setBusy(true); setError('');
        try { const created = await post<{ test_id: number }>(`/teacher/tests/${id}/session`, { request_key: sessionRequest.current }); newSession(created.test_id); }
        catch (error) { setError(message(error)); } finally { setBusy(false); }
      }}><Icon name="plus" size={17} />Yangi sessiya</button></details>}</div></details>}
    <div className="stats-grid"><div className="stat-card"><span className="stat-icon"><Icon name="users" /></span><div><span>Qatnashchilar</span><strong>{result.submissions.length}</strong></div></div><div className="stat-card"><span className="stat-icon pink"><Icon name="book" /></span><div><span>Jami savollar</span><strong>{result.test.total_questions}</strong></div></div><div className="stat-card"><span className="stat-icon amber"><Icon name="clock" /></span><div><span>Kutilmoqda</span><strong>{pending}</strong></div></div></div>
    {!!result.test.active_attempts && <Alert tone="warning">{result.test.active_attempts} o‘quvchi ishlamoqda. Yakunlash uchun ular topshirishini kuting.</Alert>}
    {result.test.status === 'active' && <section className="finish-panel"><div><h3>{pending ? 'Javoblar tekshirilmoqda' : 'Natijalarni e’lon qilish'}</h3><p>{pending ? `${pending} ta javobni tekshiring yoki AI tekshiruvini qayta boshlang.` : 'Yakunlagach, yangi javoblar yopiladi va barcha ballar hisoblanadi.'}</p></div><div className="actions"><button className="secondary" disabled={busy} onClick={() => void action('retry-grading')}><Icon name="refresh" size={17} />Qayta tekshirish</button><button className="success-action" disabled={busy || pending > 0 || Boolean(result.test.active_attempts)} onClick={async () => { if (await confirm({ title: 'Test yakunlansinmi?', description: 'Yangi javoblar qabul qilinmaydi. Savollar qiyinligi bo‘yicha ballar va o‘quvchilar reytingi hisoblanib, natijalar e’lon qilinadi.', action: 'Testni yakunlash' })) void action('finish'); }}>Testni yakunlash<Icon name="check" size={17} /></button></div></section>}
    <nav className="tabs results-tabs" aria-label="Natija bo‘limlari"><button className={view === 'participants' ? 'selected' : ''} aria-pressed={view === 'participants'} onClick={() => setView('participants')}><Icon name="users" size={17} />Qatnashchilar<span>{result.submissions.length}</span></button>{result.test.status === 'finished' && <button className={view === 'analysis' ? 'selected' : ''} aria-pressed={view === 'analysis'} onClick={() => setView('analysis')}><Icon name="chart" size={17} />Savollar tahlili</button>}</nav>
    {view === 'participants' ? <div className={'results-layout ' + (participant ? 'has-selection' : '')}><section className="card participants-card"><div className="section-heading"><h2>{result.test.status === 'finished' ? 'Yakuniy reyting' : 'Qatnashchilar'}</h2><span className="live-indicator"><span />Jonli</span></div><label className="search-field"><Icon name="search" size={17} /><input value={search} onChange={e => setSearch(e.target.value)} placeholder="O‘quvchini qidirish…" aria-label="Qatnashchilarni qidirish" /></label>{!participants.length ? <EmptyState icon="users" title={search ? 'O‘quvchi topilmadi' : 'Hali javoblar yo‘q'}>{search ? 'Boshqa ism yoki ID kiriting.' : 'Test havolasini o‘quvchilarga ulashing.'}</EmptyState> : <div className="participant-list">{participantPage.items.map(sub => <button className={'participant-row ' + (selected === sub.id ? 'participant-selected' : '')} key={sub.id} onClick={() => setSelected(sub.id)} aria-pressed={selected === sub.id}><span className="participant-avatar">{result.test.status === 'finished' ? sub.rank : (sub.first_name || 'O‘quvchi').slice(0, 1).toUpperCase()}</span><span className="participant-name"><strong>{sub.first_name} {sub.last_name || ''}</strong><small>{result.answers.some(a => a.submission_id === sub.id && a.grading_status !== 'done') ? 'Javoblar tekshirilmoqda' : 'Javoblar tekshirilgan'}</small></span><span className="participant-score"><strong>{result.test.status === 'finished' ? sub.total_score : sub.total_correct}</strong><small>{result.test.status === 'finished' ? 'ball' : 'to‘g‘ri'}</small></span><Icon name="chevron" size={16} /></button>)}</div>}<PageControls page={participantPage.page} pages={participantPage.pages} onChange={participantPage.setPage} label="Qatnashchilar sahifalari" /></section>
    {participant && <section ref={answerDetail} className="card answer-detail" aria-label="Tanlangan o‘quvchining javoblari"><div className="section-heading"><div><span className="eyebrow">O‘QUVCHI JAVOBLARI</span><h2>{participant.first_name} {participant.last_name || ''}</h2></div><button className="icon-button" aria-label="O‘quvchi javoblarini yopish" onClick={() => setSelected(null)}><Icon name="close" /></button></div><p className="muted">Telegram ID: {participant.user_id}</p>{answerPage.items.map(answer => <article className="answer-review" key={answer.id}><div className="section-heading"><strong>{answer.question_num}-savol</strong><span className={'answer-status ' + (answer.grading_status !== 'done' ? 'pending' : answer.is_correct ? 'correct' : 'incorrect')}><Icon name={answer.grading_status !== 'done' ? 'clock' : answer.is_correct ? 'check' : 'close'} size={14} />{answer.grading_status !== 'done' ? 'Tekshirilmoqda' : answer.is_correct ? 'To‘g‘ri' : 'Noto‘g‘ri'}</span></div><p className="student-written-answer">{answer.user_answer || 'Javob berilmagan'}</p>{answer.ai_feedback && <details className="feedback-disclosure"><summary>Tekshiruv izohi<Icon name="chevron" size={14} /></summary><p className="feedback-text">{answer.ai_feedback}</p></details>}{result.test.status === 'active' && <div className="override-actions"><button className="secondary answer-correct" disabled={busy} aria-pressed={answer.grading_status === 'done' && Boolean(answer.is_correct)} onClick={() => void action('answers/' + answer.id, { correct: true, feedback: 'O‘qituvchi tasdiqladi.' })}><Icon name="check" size={16} />To‘g‘ri</button><button className="secondary answer-incorrect" disabled={busy} aria-pressed={answer.grading_status === 'done' && !answer.is_correct} onClick={() => void action('answers/' + answer.id, { correct: false, feedback: 'O‘qituvchi tekshirdi.' })}><Icon name="close" size={16} />Noto‘g‘ri</button></div>}</article>)}<PageControls page={answerPage.page} pages={answerPage.pages} onChange={answerPage.setPage} label="O‘quvchi javoblari sahifalari" /></section>}</div> : <section className="card analysis-card"><div className="section-heading"><h2>Savollar bo‘yicha tahlil</h2><span className="muted">{result.questions.length} ta savol</span></div><details className="scoring-help"><summary>Ball qanday hisoblanadi?<Icon name="help" size={15} /></summary><p>Ko‘proq to‘g‘ri javob berilgan savollar osonroq hisoblanadi. Oson — 1.1, o‘rtacha — 1.7, qiyin — 2.5 ball. Ochiq savollarda belgilangan ball qo‘llanadi.</p></details>{analysisPage.items.map(q => <div className="analysis-row" key={q.question_num}><strong>{q.question_num}-savol</strong><div><div className="analysis-bar"><span style={{ width: `${result.submissions.length ? q.correct_count / result.submissions.length * 100 : 0}%` }} /></div><small>{q.correct_count} / {result.submissions.length} to‘g‘ri</small></div><span className={'tier tier-' + q.assigned_tier}>{({ easy: 'Oson', medium: 'O‘rtacha', hard: 'Qiyin' } as Record<string, string>)[q.assigned_tier || ''] || 'Ochiq'}</span><strong>{q.assigned_points ?? '—'}<small> ball</small></strong></div>)}<PageControls page={analysisPage.page} pages={analysisPage.pages} onChange={analysisPage.setPage} label="Savollar tahlili sahifalari" /></section>}
  </> : <Loading label="Natijalar yuklanmoqda…" />}</>;
}

createRoot(document.getElementById('root')!).render(<App />);
