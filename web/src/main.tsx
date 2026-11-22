import React, { useEffect, useId, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { api, post, questionAnswered, linkedImport, ApiError } from './api';
import type { Answers, ImportRecord, Passage, Question, Region, Results, StudentTest, Submission, TestDocument, TestSummary } from './types';
import { Alert, Badge, Brand, ConfirmationProvider, EmptyState, Guide, Icon, Loading, NavigationProvider, useConfirmation, useExitGuard, useMediaQuery, useNavigation, useTelegramBack } from './ui';
import './style.css';

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

function Workspace() {
  const [identity, setIdentity] = useState<{ is_admin: boolean; user: { first_name: string }; bot_import_url?: string | null } | null>(null);
  const [error, setError] = useState('');
  const [mode, setMode] = useState<'student' | 'teacher'>('student');
  const [guide, setGuide] = useState(false);
  const [loginAttempt, setLoginAttempt] = useState(0);
  const [switching, setSwitching] = useState(false);
  const [navigationError, setNavigationError] = useState('');
  const navigation = useNavigation();
  useEffect(() => { window.scrollTo({ top: 0 }); }, [mode]);
  async function switchMode(next: 'student' | 'teacher') {
    if (next === mode || switching) return;
    setSwitching(true); setNavigationError('');
    try { await navigation.leave(); setMode(next); }
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
        try { result = await api<typeof identity & object>('/me'); }
        catch { result = await post<typeof identity & object>('/session', { init_data: telegram?.initData || '' }); }
        setIdentity(result);
        if (result.is_admin && linkedImport(location.search)) setMode('teacher');
      } catch (error) { setError(message(error)); }
    };
    void login();
  }, [loginAttempt]);
  return <div className={'app-shell mode-' + mode}>
    <a className="skip-link" href="#content">Asosiy mazmunga o‘tish</a>
    <aside className="sidebar"><Brand /><div className="sidebar-label">SHAXSIY KABINET</div><nav className="workspace-nav" aria-label="Asosiy bo‘limlar">
      <button disabled={switching} className={mode === 'student' ? 'nav-active' : ''} aria-current={mode === 'student' ? 'page' : undefined} onClick={() => void switchMode('student')}><Icon name="book" />Test topshirish<Icon name="chevron" size={16} /></button>
      {identity?.is_admin && <button disabled={switching} className={mode === 'teacher' ? 'nav-active' : ''} aria-current={mode === 'teacher' ? 'page' : undefined} onClick={() => void switchMode('teacher')}><Icon name="grid" />O‘qituvchi<Icon name="chevron" size={16} /></button>}
    </nav><div className="sidebar-bottom"><div className="sidebar-note"><Icon name="spark" /><p>Har bir savol —<br /><strong>yangi imkoniyat.</strong></p></div><button className="help-link" onClick={() => setGuide(true)}><Icon name="help" />Qanday foydalaniladi?</button><span className="sidebar-copyright">Basirat · Bilim sari birga</span></div></aside>
    <div className="workspace"><header className="app-header"><div className="mobile-brand"><Brand /></div><span className="desktop-breadcrumb">Shaxsiy kabinet<Icon name="chevron" size={14} /><strong>{mode === 'teacher' ? 'O‘qituvchi' : 'Test topshirish'}</strong></span><div className="header-actions"><button className="icon-button" aria-label="Foydalanish qo‘llanmasi" onClick={() => setGuide(true)}><Icon name="help" /></button>{identity && <div className="profile"><span className="avatar">{identity.user.first_name.slice(0, 1).toUpperCase()}</span><div><strong>{identity.user.first_name}</strong><span>{identity.is_admin ? 'O‘qituvchi' : 'O‘quvchi'}</span></div></div>}</div></header>
      <main id="content">
        {navigationError && <Alert>{navigationError}</Alert>}
        {!identity ? <section className="card auth-card">{error ? <><span className="empty-icon"><Icon name="send" size={30} /></span><span className="eyebrow">BASIRAT TESTLAR</span><h1>Telegramda ko‘rishamiz.</h1><p>Test topshirish va kabinetingizga kirish uchun ilovani Telegram botidagi <strong>Testlar</strong> tugmasi orqali oching.</p><Alert>{error}</Alert><button onClick={() => setLoginAttempt(i => i + 1)}><Icon name="refresh" size={18} />Qayta ulanish</button><button className="quiet" onClick={() => setGuide(true)}>Qanday foydalaniladi?</button></> : <><Loading label="Kabinetingiz ochilmoqda…" /><p>Telegram hisobingiz tekshirilmoqda.</p></>}</section> : <>
          {identity.is_admin && <nav className="role-switch" aria-label="Kabinetni tanlash"><button disabled={switching} aria-pressed={mode === 'student'} className={mode === 'student' ? 'selected' : ''} onClick={() => void switchMode('student')}><Icon name="book" size={18} />O‘quvchi</button><button disabled={switching} aria-pressed={mode === 'teacher'} className={mode === 'teacher' ? 'selected' : ''} onClick={() => void switchMode('teacher')}><Icon name="grid" size={18} />O‘qituvchi</button></nav>}
          {mode === 'teacher' && identity.is_admin ? <Teacher botImportUrl={identity.bot_import_url} /> : <Student firstName={identity.user.first_name} />}
        </>}
      </main><footer className="workspace-footer"><span>Basirat ta’lim markazi</span><button className="quiet" onClick={() => setGuide(true)}>Yordam<Icon name="help" size={15} /></button></footer>
    </div><Guide open={guide} close={() => setGuide(false)} />
  </div>;
}

function Teacher({ botImportUrl }: { botImportUrl?: string | null }) {
  const [imports, setImports] = useState<ImportRecord[]>([]);
  const [tests, setTests] = useState<TestSummary[]>([]);
  const [selectedImport, setSelectedImport] = useState<string | null>(() => linkedImport(location.search));
  const [selectedTest, setSelectedTest] = useState<number | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [list, setList] = useState<'tests' | 'imports'>('tests');
  const [search, setSearch] = useState('');
  const [loaded, setLoaded] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  useEffect(() => { window.scrollTo({ top: 0 }); }, [selectedImport, selectedTest]);
  async function refresh() {
    try {
      const [a, b] = await Promise.all([api<ImportRecord[]>('/admin/imports'), api<TestSummary[]>('/admin/tests')]);
      setImports(a); setTests(b); setLoaded(true);
    } catch (error) { setError(message(error)); }
  }
  useEffect(() => { void refresh(); const timer = setInterval(() => void refresh(), 5000); return () => clearInterval(timer); }, []);
  async function upload() {
    setBusy(true); setError('');
    try {
      const data = new FormData(); files.forEach(file => data.append('files', file));
      const created = await api<{ id: string }>('/admin/imports', { method: 'POST', body: data });
      setFiles([]); setSelectedImport(created.id); await refresh();
    } catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  if (selectedImport) return <ImportEditor id={selectedImport} back={() => { setSelectedImport(null); void refresh(); }} published={id => { setSelectedImport(null); setSelectedTest(id); void refresh(); }} />;
  if (selectedTest) return <TeacherResults id={selectedTest} back={() => setSelectedTest(null)} />;
  const filteredTests = tests.filter(test => `${test.title} ${test.code}`.toLocaleLowerCase().includes(search.toLocaleLowerCase()));
  const filteredImports = imports.filter(item => item.title.toLocaleLowerCase().includes(search.toLocaleLowerCase()));
  function goToUpload() { setUploadOpen(true); requestAnimationFrame(() => window.document.getElementById('local-upload')?.scrollIntoView({ behavior: 'smooth', block: 'center' })); }
  return <>
    <div className="page-heading"><div><span className="eyebrow">O‘QITUVCHI KABINETI</span><h1>Bilimni baholash,<br className="mobile-only" /> yanada qulay.</h1><p>Test yarating, javoblarni tekshiring va natijalarni kuzating.</p></div><button className="secondary" onClick={goToUpload}><Icon name="plus" size={18} />Yangi test</button></div>
    <div className="stats-grid"><div className="stat-card"><span className="stat-icon"><Icon name="book" /></span><div><span>Jami testlar</span><strong>{loaded ? tests.length : '—'}</strong></div></div><div className="stat-card"><span className="stat-icon green"><Icon name="chart" /></span><div><span>Faol testlar</span><strong>{loaded ? tests.filter(t => t.status === 'active').length : '—'}</strong></div></div><div className="stat-card"><span className="stat-icon pink"><Icon name="edit" /></span><div><span>Tekshirishga tayyor</span><strong>{loaded ? imports.filter(i => i.status === 'review').length : '—'}</strong></div></div></div>
    <section className="upload-panel" id="upload-panel"><div className="upload-copy"><span className="eyebrow"><Icon name="spark" size={15} />AI YORDAMIDA TEST YARATISH</span><h2>Tayyor testdan boshlang.</h2><p>PDF yoki rasmlarni yuboring. AI savollarni ajratadi,<br className="desktop-only" /> siz tekshirib, o‘quvchilarga taqdim etasiz.</p>
      <button onClick={() => {
        const telegram = window.Telegram?.WebApp;
        if (botImportUrl) {
          if (telegram?.openTelegramLink) telegram.openTelegramLink(botImportUrl);
          else { location.assign(botImportUrl); return; }
        }
        telegram?.close();
      }}><Icon name="send" size={18} />Telegram orqali yuborish<Icon name="arrow" size={18} /></button>
      <span className="upload-hint">PDF yoki rasmlarni boshqa chatdan yuborishingiz ham mumkin.</span>
    </div><div className="document-art" aria-hidden="true"><div className="art-page art-page-back" /><div className="art-page"><span className="art-file-label">BASIRAT · TEST</span><span className="art-line" /><span className="art-line short" /><span className="art-question"><i>A</i><b /></span><span className="art-question"><i>B</i><b /></span><span className="art-question art-checked"><i><Icon name="check" size={11} /></i><b /></span><span className="art-line short" /></div><span className="art-spark"><Icon name="spark" size={26} /></span></div></section>
    <section className="card local-upload" id="local-upload"><details open={uploadOpen} onToggle={event => setUploadOpen(event.currentTarget.open)}><summary><span><Icon name="upload" size={18} />Qurilmadan fayl yuklash</span><Icon name="plus" size={18} /></summary><p>Fayl telefonda yoki kompyuterda saqlanganmi? Shu yerdan tanlang.</p><div className="file-picker-grid"><label className="file-picker"><Icon name="file" size={26} /><strong>PDF hujjat</strong><span>Bitta PDF tanlang</span><input aria-label="PDF hujjat" type="file" accept=".pdf,application/pdf" disabled={busy} onChange={e => { setFiles(Array.from(e.target.files || [])); e.target.value = ''; }} /></label><label className="file-picker"><Icon name="image" size={26} /><strong>Sahifa rasmlari</strong><span>JPG, PNG yoki WebP</span><input aria-label="Sahifa rasmlari" type="file" accept="image/*" multiple disabled={busy} onChange={e => { setFiles(Array.from(e.target.files || [])); e.target.value = ''; }} /></label></div>
      {!!files.length && <ol className="file-list">{files.map((file, i) => <li key={i}><span className="file-order">{i + 1}</span><span>{file.name}<small>{(file.size / 1024 / 1024).toFixed(1)} MB</small></span>{i > 0 && <button className="icon-button" aria-label={`${file.name} faylini oldinga ko‘chirish`} onClick={() => setFiles(list => { const next = [...list]; [next[i - 1], next[i]] = [next[i], next[i - 1]]; return next; })}>↑</button>}<button className="icon-button" aria-label={`${file.name} faylini olib tashlash`} onClick={() => setFiles(list => list.filter((_, n) => n !== i))}><Icon name="close" size={17} /></button></li>)}</ol>}
      <div className="upload-bottom"><span className="muted">Jami 20 MB gacha · Ko‘pi bilan 30 sahifa</span><button disabled={!files.length || busy} onClick={() => void upload()}>{busy ? <><span className="spinner" />Yuklanmoqda…</> : <><Icon name="spark" size={17} />Savollarni ajratish</>}</button></div></details></section>
    {error && <Alert>{error}</Alert>}
    <section className="card library"><div className="library-header"><nav className="tabs" aria-label="Testlar ro‘yxati"><button className={list === 'tests' ? 'selected' : ''} aria-pressed={list === 'tests'} onClick={() => setList('tests')}>Testlar<span>{tests.length}</span></button><button className={list === 'imports' ? 'selected' : ''} aria-pressed={list === 'imports'} onClick={() => setList('imports')}>Qoralamalar<span>{imports.length}</span></button></nav><label className="search-field"><Icon name="search" size={17} /><input aria-label="Testlarni qidirish" placeholder="Nom yoki kod bo‘yicha qidirish" value={search} onChange={e => setSearch(e.target.value)} /></label></div>
      {!loaded ? <Loading /> : list === 'tests' ? !filteredTests.length ? <EmptyState title={search ? 'Test topilmadi' : 'Birinchi testingizni yarating'} action={!search && <button className="secondary" onClick={goToUpload}><Icon name="plus" size={17} />Test qo‘shish</button>}>{search ? 'Boshqa nom yoki kod bilan qidirib ko‘ring.' : 'Tayyor PDF yoki rasmlarni yuklang. Nashr qilingan testlaringiz shu yerda bo‘ladi.'}</EmptyState> : <div className="test-list">{filteredTests.map(test => <button className="test-list-row" key={test.id} onClick={() => setSelectedTest(test.id)}><span className="list-icon"><Icon name="book" /></span><span className="list-title"><strong>{test.title}</strong><span><code>{test.code}</code><span className="dot-separator">·</span>{test.total_questions} ta savol</span></span><Badge status={test.status} /><Icon name="chevron" size={18} /></button>)}</div> : !filteredImports.length ? <EmptyState icon="file" title={search ? 'Qoralama topilmadi' : 'Hali qoralamalar yo‘q'}>{search ? 'Boshqa nom bilan qidirib ko‘ring.' : 'Yuborgan fayllaringiz va AI ajratgan savollar shu yerda saqlanadi.'}</EmptyState> : <div className="test-list">{filteredImports.map(item => <button className="test-list-row" key={item.id} onClick={() => setSelectedImport(item.id)}><span className="list-icon"><Icon name="file" /></span><span className="list-title"><strong>{item.title}</strong><span>{['processing', 'queued'].includes(item.status) ? `${item.progress}% tayyor` : item.document ? `${item.document.questions.length} ta savol` : 'PDF va rasmlardan test'}</span></span><Badge status={item.status} /><Icon name="chevron" size={18} /></button>)}</div>}
    </section>
    <div className="teacher-tip"><Icon name="shield" size={19} /><p>Test faqat siz savollar va javoblarni tekshirib, nashr qilganingizdan keyin o‘quvchilarga ochiladi.</p></div>
  </>;
}

function ImportEditor({ id, back, published }: { id: string; back(): void; published(id: number): void }) {
  const confirm = useConfirmation();
  const wideSource = useMediaQuery('(min-width: 1251px)');
  const [record, setRecord] = useState<ImportRecord | null>(null);
  const [document, setDocument] = useState<TestDocument | null>(null);
  const revision = useRef(0);
  const latestDocument = useRef<TestDocument | null>(null);
  const savedDocument = useRef('');
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
      const item = await api<ImportRecord>('/admin/imports/' + id);
      setRecord(item);
      if (item.document && !latestDocument.current) { setDocument(item.document); latestDocument.current = item.document; revision.current = item.revision; savedDocument.current = JSON.stringify(item.document); }
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
  }, [document, dirty, busy]);
  function change(next: TestDocument) { latestDocument.current = next; setDocument(next); setDirty(true); setNotice(''); }
  async function save() {
    while (saving.current) await saving.current;
    if (!latestDocument.current) return revision.current;
    if (conflict.current) throw new Error('Qoralama boshqa oynada o‘zgargan. O‘zgarishlaringizni nusxalab, qayta oching.');
    const serialized = JSON.stringify(latestDocument.current);
    if (serialized === savedDocument.current) return revision.current;
    const task = (async () => {
      try {
        const result = await api<{ revision: number }>('/admin/imports/' + id, { method: 'PUT', body: JSON.stringify({ document: JSON.parse(serialized), revision: revision.current }) });
        revision.current = result.revision; savedDocument.current = serialized;
        setDirty(JSON.stringify(latestDocument.current) !== serialized); setNotice('Qoralama saqlandi.');
        return result.revision;
      } catch (error) { if (error instanceof ApiError && error.status === 409) conflict.current = true; throw error; }
    })();
    saving.current = task;
    try { return await task; } finally { saving.current = null; }
  }
  useExitGuard(async () => { await save(); });
  async function act(publish = false) {
    setBusy(true); setError('');
    try {
      const current = await save();
      if (publish) {
        const result = await post<{ test_id: number }>('/admin/imports/' + id + '/publish', { revision: current });
        published(result.test_id);
      }
    } catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  function updateQuestion(question: Question) {
    if (!document) return;
    change({ ...document, questions: document.questions.map((q, i) => i === questionIndex ? question : q) });
  }
  const q = document?.questions[questionIndex];
  const sourcePage = q?.source_pages[0] || record?.assets.find(a => a.kind === 'page')?.page || 1;
  const [visiblePage, setVisiblePage] = useState(0);
  const pages = record?.assets.filter(a => a.kind === 'page') || [];
  const page = pages.find(a => a.page === (visiblePage || sourcePage));
  const reviewed = document?.questions.filter(q => q.reviewed).length || 0;
  const fullyReviewed = Boolean(document && document.questions.length >= 5 && reviewed === document.questions.length);
  async function leave() { setBusy(true); try { await save(); back(); } catch (error) { setError(message(error)); } finally { setBusy(false); } }
  useTelegramBack(() => { if (!busy) void leave(); });
  return <>
    <button className="back-link" disabled={busy} onClick={() => void leave()}><Icon name="back" size={17} />O‘qituvchi kabineti</button>
    <div className="page-heading"><div><span className="eyebrow">TEST TAYYORLASH</span><h1>Savollarni tekshiramiz.</h1><p>Asl hujjat bilan solishtiring, javoblarni belgilang va tasdiqlang.</p></div>{record && <Badge status={record.status} />}</div>
    <ol className="workflow-steps" aria-label="Test yaratish bosqichlari"><li className="done"><span><Icon name="check" size={14} /></span>Fayl yuklash</li><li className={document ? 'done' : 'current'}><span>{document ? <Icon name="check" size={14} /> : '2'}</span>AI ajratishi</li><li className={document ? 'current' : ''}><span>3</span>Tekshirish</li><li className={record?.status === 'published' ? 'done' : ''}><span>4</span>Nashr qilish</li></ol>
    {error && <Alert>{error}</Alert>}
    {notice && !dirty && <div className="save-notice" role="status"><Icon name="check" size={14} />{notice}</div>}
    {!record ? <Loading /> : record.status === 'published' ? <section className="card"><EmptyState icon="check" title="Testingiz tayyor!" action={<button onClick={() => published(record.published_test_id!)}>Test va natijalar<Icon name="arrow" size={17} /></button>}>Endi test kodini o‘quvchilarga yuborishingiz mumkin.</EmptyState></section> : !document ? <section className="card processing-card"><span className="processing-icon"><Icon name={record.status === 'failed' ? 'refresh' : record.status === 'collecting' ? 'image' : 'spark'} size={32} /></span><Badge status={record.status} /><h2>{record.status === 'collecting' ? 'Sahifalarni yig‘amiz.' : record.status === 'failed' ? 'Yana bir bor urinib ko‘ramiz.' : 'Testingiz tayyorlanmoqda.'}</h2><p className="muted">{record.title}</p><div className="progress-label"><span>Tayyorlanish jarayoni</span><strong>{record.progress}%</strong></div><progress aria-label="Testni ajratish jarayoni" value={record.progress} max={100} />{record.status === 'collecting' ? <><p>{record.assets.filter(a => a.kind === 'source').length} ta rasm qabul qilindi. Qolgan sahifalarni botga yuboring, so‘ng ajratishni boshlang.</p><button disabled={busy} onClick={async () => { setBusy(true); setError(''); try { await post('/admin/imports/' + id + '/start'); await load(); } catch (error) { setError(message(error)); } finally { setBusy(false); } }}><Icon name="spark" size={18} />Savollarni ajratish</button></> : <p>{record.error || 'Savollar, umumiy matnlar va rasmlar ajratilmoqda. Ilovani yopishingiz mumkin — tayyor bo‘lgach, bot xabar beradi.'}</p>}{record.status === 'failed' && <button disabled={busy} onClick={async () => { setBusy(true); try { await post('/admin/imports/' + id + '/retry'); await load(); } catch (error) { setError(message(error)); } finally { setBusy(false); } }}><Icon name="refresh" size={18} />Qayta urinish</button>}</section> : <fieldset className="editor-fields" disabled={busy}>
      <section className="card document-overview"><div className="overview-top"><span className="list-icon"><Icon name="file" size={23} /></span><div><span className="eyebrow">TEST MA’LUMOTLARI</span><Field label="Test nomi" rows={1} value={document.title} onChange={title => change({ ...document, title })} /></div></div>
        <div className="document-meta"><span><strong>{document.questions.length}</strong> ta savol</span><span><strong>{document.questions.filter(q => q.kind === 'open').length}</strong> ta ochiq javob</span><span className="reviewed-count"><Icon name="check" size={16} /><strong>{reviewed}/{document.questions.length}</strong> tasdiqlangan</span></div>
        {!!document.warnings.length && <details className="warning-details"><summary><Icon name="help" size={16} />E’tibor talab qiladi ({document.warnings.length})</summary><ul>{document.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul></details>}
        <details className="bulk-keys"><summary><Icon name="grid" size={16} />Javoblar kalitini birga kiritish<Icon name="plus" size={16} /></summary><p className="muted">Variantli savollar kalitlarini tez kiriting. Keyin har bir savolni alohida tekshirib tasdiqlang.</p><Field label="Javoblar kaliti" placeholder="1:A, 2:F, 3:B" value={keys} onChange={setKeys} /><button className="secondary" onClick={() => {
          const pairs = Array.from(keys.matchAll(/(\d{1,2})\s*[.\-:)]\s*([A-F])/gi));
          if (!pairs.length) { setError('Kalitlar topilmadi. 1:A, 2:F formatidan foydalaning.'); return; }
          const mapping = Object.fromEntries(pairs.map(p => [Number(p[1]), p[2].toUpperCase()]));
          change({ ...document, questions: document.questions.map(q => q.kind !== 'open' && mapping[q.number] ? { ...q, answer: mapping[q.number], reviewed: false } : q) });
          setNotice('Kalitlar kiritildi. Har bir savolni tekshirib tasdiqlang.');
        }}>Kalitlarni qo‘llash</button></details>
      </section>
      <nav className="tabs editor-tabs" aria-label="Tahrirlash bo‘limlari"><button className={tab === 'questions' ? 'selected' : ''} aria-pressed={tab === 'questions'} onClick={() => setTab('questions')}><Icon name="grid" size={17} />Savollar<span>{document.questions.length}</span></button><button className={tab === 'passages' ? 'selected' : ''} aria-pressed={tab === 'passages'} onClick={() => setTab('passages')}><Icon name="book" size={17} />Umumiy matnlar<span>{document.passages.length}</span></button></nav>
      <div className="editor-layout"><div className="editor-main">
        {tab === 'questions' ? <section className="card">
          <div className="section-heading"><h2>Savolni tahrirlash</h2><span className="muted">{questionIndex + 1} / {document.questions.length}</span></div><nav className="question-nav" aria-label="Tahrirlash uchun savolni tanlang">{document.questions.map((q, i) => <button key={i} aria-label={`${q.number}-savol${q.reviewed ? ', tasdiqlangan' : ''}`} aria-current={i === questionIndex ? 'step' : undefined} className={i === questionIndex ? 'selected' : q.reviewed ? 'complete' : 'secondary'} onClick={() => { setQuestionIndex(i); setVisiblePage(0); }}>{q.number}</button>)}</nav>
          {q && <QuestionEditor key={questionIndex} question={q} passages={document.passages} pages={pages} update={updateQuestion} />}
          <div className="actions editor-question-actions"><button className="secondary" disabled={document.questions.length >= 44} onClick={() => { const number = Array.from({ length: 44 }, (_, i) => i + 1).find(n => !document.questions.some(q => q.number === n))!; change({ ...document, questions: [...document.questions, newQuestion(number)] }); setQuestionIndex(document.questions.length); }}><Icon name="plus" size={16} />Savol qo‘shish</button>{q && <button className="danger" onClick={async () => { if (await confirm({ title: 'Savol o‘chirilsinmi?', description: `${q.number}-savol va uning javob mezoni qoralamadan olib tashlanadi.`, action: 'Savolni o‘chirish', danger: true })) { change({ ...document, questions: document.questions.filter((_, i) => i !== questionIndex) }); setQuestionIndex(0); } }}>O‘chirish</button>}</div>
        </section> : <section className="card">{document.passages.map((p, i) => <PassageEditor key={i} passage={p} pages={pages} update={next => change({ ...document, passages: document.passages.map((p, n) => i === n ? next : p), questions: document.questions.map(q => q.passage_id === p.id ? { ...q, reviewed: false } : q) })} remove={() => change({ ...document, passages: document.passages.filter((_, n) => n !== i) })} />)}<button onClick={() => change({ ...document, passages: [...document.passages, { id: 'p' + Date.now(), title: '', text: '', media: [], source_pages: [] }] })}>Matn qo‘shish</button></section>}
      </div><aside className="card source"><details open={wideSource}><summary><span><Icon name="file" size={18} />Asl hujjat</span><Icon name="chevron" size={17} /></summary><label className="field">Sahifani tanlang<select value={page?.page || ''} onChange={e => setVisiblePage(Number(e.target.value))}>{pages.map(p => <option key={p.id} value={p.page}>{p.page}-sahifa</option>)}</select></label>{page && <a className="source-image" href={assetUrl(page.id)} target="_blank" rel="noreferrer"><img src={assetUrl(page.id)} alt={`${page.page}-sahifa — kattalashtirish uchun bosing`} /><span><Icon name="search" size={16} />Kattalashtirish</span></a>}<p className="muted">Asldagi ataylab yozilgan imlo xatolarini saqlang.</p></details></aside></div>
      <footer className="sticky editor-footer"><div><span className={'save-state ' + (dirty ? 'saving' : '')}><Icon name={dirty ? 'clock' : 'check'} size={15} />{busy ? 'Saqlanmoqda…' : dirty ? 'Avtomatik saqlanmoqda…' : 'Qoralama saqlangan'}</span><small>{fullyReviewed ? 'Barcha savollar tasdiqlangan. Nashr qilish mumkin.' : `${document.questions.length - reviewed} ta savolni tekshirib tasdiqlang.`}</small></div><div className="actions"><button className="secondary" disabled={busy} onClick={() => void act()}>Saqlash</button><button disabled={busy || !fullyReviewed} onClick={async () => { if (await confirm({ title: 'Test nashr qilinsinmi?', description: 'O‘quvchilar test kodi orqali javob bera oladi. Nashr qilingach, savollar va javob mezonlari o‘zgarmaydi.', action: 'Nashr qilish' })) void act(true); }}><Icon name="send" size={17} />Nashr qilish</button></div></footer>
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

function QuestionEditor({ question: q, passages, pages, update }: { question: Question; passages: Passage[]; pages: PageAsset[]; update(q: Question): void }) {
  const patch = (value: Partial<Question>) => update({ ...q, ...value, reviewed: false });
  return <>
    <div className="row"><label>Savol raqami<input type="number" min="1" max="44" value={q.number} onChange={e => patch({ number: Number(e.target.value) })} /></label><label>Turi<select value={q.kind} onChange={e => { const kind = e.target.value as Question['kind']; patch({ kind, options: kind === 'open' ? [] : q.options.length ? q.options : [{ label: 'A', text: '' }, { label: 'B', text: '' }], parts: kind === 'open' ? q.parts : [], answer: '' }); }}><option value="choice">Variantli</option><option value="matching">Moslashtirish</option><option value="open">Ochiq</option></select></label></div>
    {!!q.warnings.length && <Alert tone="warning">{q.warnings.join('\n')}</Alert>}
    <Field label="Savol matni" rows={5} placeholder="Savolning to‘liq matnini kiriting…" value={q.text} onChange={text => patch({ text })} />
    <p className="field-hint">Formatlash: **qalin**, *kursiv*, &lt;u&gt;tagiga chizish&lt;/u&gt;</p>
    <details><summary>Matn ko‘rinishi</summary><RichText text={q.text} /></details>
    <label className="field">Umumiy matn<select value={q.passage_id || ''} onChange={e => patch({ passage_id: e.target.value || null })}><option value="">Alohida savol</option>{passages.map(p => <option key={p.id} value={p.id}>{p.title || p.id}</option>)}</select></label>
    {q.kind !== 'open' ? <>
      <h3 className="field-heading">Javob variantlari</h3>{q.options.map((option, index) => <div className="option-editor" key={index}><b>{option.label}</b><textarea aria-label={`${option.label} variant matni`} rows={2} value={option.text} onChange={e => patch({ options: q.options.map((o, i) => i === index ? { ...o, text: e.target.value } : o) })} /><button className="icon-button" aria-label={`${option.label} variantini o‘chirish`} onClick={() => patch({ options: q.options.filter((_, i) => i !== index) })}><Icon name="close" size={16} /></button></div>)}
      <button className="secondary" disabled={q.options.length >= 6} onClick={() => { const label = 'ABCDEF'.split('').find(label => !q.options.some(o => o.label === label))!; patch({ options: [...q.options, { label, text: '' }] }); }}>Variant qo‘shish</button>
      <label className="field">To‘g‘ri javob<select value={q.answer} onChange={e => patch({ answer: e.target.value })}><option value="">Tanlang</option>{q.options.map(o => <option key={o.label}>{o.label}</option>)}</select></label>
    </> : <>
      {q.parts.map((part, index) => <div className="option-editor" key={part.id}><b>{part.id})</b><textarea aria-label={`${part.id} qism matni`} value={part.prompt} onChange={e => patch({ parts: q.parts.map((p, i) => i === index ? { ...p, prompt: e.target.value } : p) })} /><button className="icon-button" aria-label={`${part.id} qismini o‘chirish`} onClick={() => patch({ parts: q.parts.filter((_, i) => i !== index) })}><Icon name="close" size={16} /></button></div>)}
      <button className="secondary" disabled={q.parts.length >= 6} onClick={() => patch({ parts: [...q.parts, { id: 'abcdef'.split('').find(id => !q.parts.some(p => p.id === id))!, prompt: '' }] })}>a/b qism qo‘shish</button>
      <Field label="O‘qituvchi tasdiqlagan javob va tekshirish mezoni" rows={5} value={q.rubric} onChange={rubric => patch({ rubric })} />
      {!q.parts.length && <Field label="Aniq qabul qilinadigan javoblar · har biri yangi qatorda" value={q.accepted_answers.join('\n')} onChange={value => patch({ accepted_answers: value.split('\n') })} />}
      <label className="field">Savol uchun ball<input type="number" min="0.1" max="100" step="0.1" value={q.points} onChange={e => patch({ points: Number(e.target.value) })} /></label>
      {!!q.parts.length && <p className="muted">Barcha qismlar to‘g‘ri bo‘lsa, bu bitta savol uchun {q.points} ball beriladi.</p>}
    </>}
    <RegionEditor regions={q.media} pages={pages} update={media => patch({ media })} />
    <label className={'check ' + (q.reviewed ? 'is-checked' : '')}><input type="checkbox" checked={q.reviewed} onChange={e => update({ ...q, reviewed: e.target.checked })} /><span><strong>Savolni tekshirdim</strong><small>Matn, rasm va to‘g‘ri javob mezoni asl hujjatga mos.</small></span></label>
  </>;
}

function PassageEditor({ passage: p, pages, update, remove }: { passage: Passage; pages: PageAsset[]; update(p: Passage): void; remove(): void }) {
  const confirm = useConfirmation();
  return <article className="passage-editor"><p className="eyebrow">UMUMIY MATN · {p.id}</p><Field label="Matn sarlavhasi" value={p.title} rows={1} onChange={title => update({ ...p, title })} /><Field label="Umumiy matn, izohlar va lug‘at" value={p.text} rows={12} onChange={text => update({ ...p, text })} /><RegionEditor regions={p.media} pages={pages} update={media => update({ ...p, media })} /><button className="danger" onClick={async () => { if (await confirm({ title: 'Umumiy matn o‘chirilsinmi?', description: 'Matnga bog‘langan savollarni ham tekshirib chiqishingiz kerak bo‘ladi.', action: 'Matnni o‘chirish', danger: true })) remove(); }}>Matnni o‘chirish</button></article>;
}

function Student({ firstName }: { firstName: string }) {
  const initialCode = new URLSearchParams(location.search).get('test') || window.Telegram?.WebApp.initDataUnsafe?.start_param || '';
  const [code, setCode] = useState(initialCode);
  const [test, setTest] = useState<StudentTest | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function join(value = code) {
    setBusy(true); setError('');
    try { setTest(await api<StudentTest>('/tests/' + encodeURIComponent(value.trim().toUpperCase().replace(/^(\d{4,6})$/, 'T-$1')))); }
    catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  useEffect(() => { if (initialCode) void join(initialCode); }, []);
  useEffect(() => { window.scrollTo({ top: 0 }); }, [test?.id]);
  if (test) return <Attempt key={test.id} initial={test} back={() => setTest(null)} />;
  return <div className="student-home"><section className="welcome-banner"><div><span className="eyebrow">BASIRAT BILAN BIRGA</span><p className="welcome-greeting">Assalomu alaykum, {firstName}!</p><h1>Tayyor bo‘lsangiz,<br />boshlaymiz.</h1><p>Bilimingizni sinang. O‘z ustingizda ishlang.<br />Har safar bir qadam oldinga.</p><span className="welcome-tag"><Icon name="book" size={15} />Bilim sari birga</span></div><div className="brand-illustration" aria-hidden="true"><div className="orbit orbit-one" /><div className="orbit orbit-two" /><img src="/basirat-logo.png" alt="" /><span className="brand-star star-one">✦</span><span className="brand-star star-two">✦</span></div></section>
    <div className="join-layout"><section className="card join"><div className="section-heading"><span className="section-number">01</span><span className="muted">Boshlash uchun bir qadam</span></div><h2>Testga qo‘shiling</h2><p>O‘qituvchingiz bergan kodni kiriting.<br />Savollar va javoblar shu yerda ochiladi.</p><form onSubmit={e => { e.preventDefault(); void join(); }}><label htmlFor="test-code">Test kodi</label><div className="code-input"><Icon name="grid" size={21} /><input id="test-code" value={code} onChange={e => setCode(e.target.value)} placeholder="T-123456" autoCapitalize="characters" autoComplete="off" spellCheck={false} aria-describedby="code-hint" required /></div><p id="code-hint" className="field-hint">Harf bilan yoki faqat raqamlarni kiritishingiz mumkin.</p>{error && <Alert>{error}</Alert>}<button className="full-width" disabled={busy || !code.trim()}>{busy ? <><span className="spinner" />Test ochilmoqda…</> : <>Testni ochish<Icon name="arrow" size={19} /></>}</button></form><div className="join-footnote"><Icon name="shield" size={16} />Javoblaringiz faqat siz va o‘qituvchingizga ko‘rinadi.</div></section>
    <aside className="how-it-works"><span className="eyebrow">SIZ UCHUN QULAY</span><h2>E’tibor — bilimda.</h2><div className="benefit"><span><Icon name="edit" /></span><div><h3>O‘z sur’atingizda ishlang</h3><p>Savollar orasida erkin o‘ting. Javoblarni topshirishdan oldin tekshiring.</p></div></div><div className="benefit"><span><Icon name="check" /></span><div><h3>Javoblar saqlanib boradi</h3><p>Avtomatik saqlash holatini test oynasida kuzatishingiz mumkin.</p></div></div><div className="benefit"><span><Icon name="chart" /></span><div><h3>Natijangizni bilib oling</h3><p>Javoblar tekshiriladi. Yakuniy ball va o‘rin test tugagach ko‘rinadi.</p></div></div></aside></div><div className="student-bottom-note"><span />O‘rganishdan to‘xtamang.<span /></div>
  </div>;
}

function Attempt({ initial, back }: { initial: StudentTest; back(): void }) {
  const [answers, setAnswers] = useState<Answers>(initial.draft);
  const [result, setResult] = useState<Submission | null>(initial.submission);
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
    if (serialized === saved.current || result) return;
    if (conflict.current) throw new Error('Javoblar boshqa oynada o‘zgargan. Qayta ochishdan oldin javoblaringizni nusxalang.');
    const task = (async () => {
      setSaveState('Saqlanmoqda…');
      try {
        const value = await post<{ revision: number }>('/tests/' + initial.code + '/draft', { answers: JSON.parse(serialized), revision: revision.current });
        revision.current = value.revision; saved.current = serialized; setSaveState(JSON.stringify(latest.current) === serialized ? 'Saqlangan' : 'Saqlanmoqda…');
      } catch (error) { if (error instanceof ApiError && error.status === 409) conflict.current = true; setSaveState('Saqlanmadi · qayta uriniladi'); throw error; }
    })();
    saving.current = task;
    try { await task; } finally { saving.current = null; }
  }
  useExitGuard(flush);
  useTelegramBack(() => { if (busy) return; if (review && !result) { setReview(false); return; } if (result) back(); else void flush().then(back).catch(error => setError(message(error))); });
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
    const next = { ...latest.current, [q.number]: value }; latest.current = next; setAnswers(next); setSaveState('Saqlanmoqda…'); setError('');
  }
  async function submit() {
    setBusy(true); setError('');
    try { await flush(); const submission = await post<Submission>('/tests/' + initial.code + '/submit', { answers: latest.current }); setResult(submission); }
    catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  const count = questions.filter(q => questionAnswered(q.parts, answers[q.number])).length;
  const passage = initial.document.passages.find(p => p.id === q?.passage_id);
  const currentAnswer = answers[q?.number];
  const currentParts = typeof currentAnswer === 'object' ? currentAnswer : {};
  function goTo(next: number) {
    const passageChanged = questions[next]?.passage_id && questions[next].passage_id !== q?.passage_id;
    setIndex(next); setReview(false);
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
    <button className="back-link" disabled={busy} onClick={() => { if (result) back(); else void flush().then(back).catch(error => setError(message(error))); }}><Icon name="back" size={17} />Testga kirish</button>
    <section className="attempt-heading"><div><div className="actions"><code>{initial.code}</code><span className="muted">{questions.length} ta savol</span></div><h1>{initial.document.title}</h1></div>{!result && <span className={'save-state ' + (saveState !== 'Saqlangan' ? 'saving' : '')} role="status"><Icon name={saveState === 'Saqlangan' ? 'check' : 'clock'} size={15} />{saveState}</span>}</section>
    {error && <Alert>{error}</Alert>}
    {result ? <StudentResult result={result} back={back} /> : initial.status !== 'active' ? <section className="card"><EmptyState icon="clock" title="Test yakunlangan" action={<button className="secondary" onClick={back}>Boshqa testga kirish</button>}>Bu testga yangi javoblar qabul qilinmaydi.</EmptyState></section> : review ? <>
      <section className="card review-summary"><span className="eyebrow">YAKUNIY TEKSHIRUV</span><h2>Hammasi tayyormi?</h2><p>Javobni o‘zgartirish uchun savol ustiga bosing. Tasdiqlagach, javoblarni o‘zgartirib bo‘lmaydi.</p><div className="review-counts"><span><strong>{count}</strong> javob berilgan</span><span className={count < questions.length ? 'unanswered-count' : ''}><strong>{questions.length - count}</strong> to‘liq javobsiz</span></div>{count < questions.length && <Alert tone="warning">{questions.length - count} ta savol to‘liq javobsiz. Bo‘sh yoki to‘liq bo‘lmagan javoblar noto‘g‘ri hisoblanadi.</Alert>}</section>
      <section className="card review-list"><div className="section-heading"><h2>Javoblaringiz</h2><span className="muted">{questions.length} ta savol</span></div>{questions.map((q, i) => <button className="review-row" disabled={busy} key={q.number} onClick={() => goTo(i)}><span className={'review-number ' + (questionAnswered(q.parts, answers[q.number]) ? 'answered' : '')}>{q.number}</span><span><strong>{q.number}-savol</strong><span className="answer-preview">{answerPreview(answers[q.number], q.parts)}</span></span><Icon name="edit" size={17} /></button>)}</section><footer className="sticky attempt-footer"><button className="secondary" disabled={busy} onClick={() => setReview(false)}><Icon name="back" size={17} />Savollarga qaytish</button><button disabled={busy} onClick={() => void submit()}>{busy ? <><span className="spinner" />Topshirilmoqda…</> : <>Tasdiqlash va topshirish<Icon name="send" size={17} /></>}</button></footer>
    </> : q && <>
      <div className="attempt-progress"><div className="progress-label"><span><strong>{count}</strong> / {questions.length} javob berilgan</span><button className="quiet" onClick={() => setReview(true)}>Javoblarim<Icon name="arrow" size={15} /></button></div><progress aria-label="Javob berilgan savollar" value={count} max={questions.length} /></div>
      <div className="attempt-layout"><aside className={'card question-map ' + (navOpen ? 'map-open' : '')}><button className="map-toggle" onClick={() => setNavOpen(value => !value)} aria-expanded={navOpen || wideMap} aria-controls="question-map"><span><Icon name="grid" size={18} />Savollar</span><span>{index + 1}/{questions.length}<Icon name="chevron" size={16} /></span></button><div className="map-content" id="question-map"><nav className="question-nav" aria-label="Savollar orasida o‘tish">{questions.map((question, i) => <button key={question.number} aria-current={i === index ? 'step' : undefined} aria-label={`${question.number}-savol${questionAnswered(question.parts, answers[question.number]) ? ', javob berilgan' : ', javobsiz'}`} className={i === index ? 'selected' : questionAnswered(question.parts, answers[question.number]) ? 'complete' : 'secondary'} onClick={() => goTo(i)}>{question.number}</button>)}</nav><div className="map-legend"><span><i className="legend-current" />Hozirgi savol</span><span><i className="legend-answered" />Javob berilgan</span><span><i />Javobsiz</span></div><p className="map-note"><Icon name="shield" size={17} />Topshirmaguningizcha javoblarni o‘zgartira olasiz.</p></div></aside><div ref={attemptMain} className="attempt-main">
      {passage && <details className="card passage" open><summary><span><Icon name="book" size={18} />{passage.title || 'Savol uchun umumiy matn'}</span><Icon name="chevron" size={17} /></summary><div className="passage-content"><RichText text={passage.text} />{passage.media.map(id => <img className="question-image" key={id} src={assetUrl(id)} alt="Matnga tegishli rasm" />)}</div></details>}
      <section className="card question-card"><div className="section-heading"><span className="eyebrow">{String(q.number).padStart(2, '0')}-SAVOL</span><span className="question-kind">{q.kind === 'open' ? 'Ochiq javob' : q.kind === 'matching' ? 'Moslashtirish' : 'Variantli savol'}</span></div><h2 ref={questionHeading} tabIndex={-1} className="question-text"><RichText text={q.text} /></h2>{q.media.map(id => <img className="question-image" key={id} src={assetUrl(id)} alt="Savol diagrammasi" />)}
        {q.kind !== 'open' ? <fieldset className="choices"><legend>Bitta javobni tanlang</legend>{q.options.map(option => <label className={answers[q.number] === option.label ? 'chosen' : ''} key={option.label}><input type="radio" name={'q' + q.number} checked={answers[q.number] === option.label} onChange={() => change(option.label)} /><span className="choice-letter">{option.label}</span><RichText text={option.text} /><span className="choice-indicator"><Icon name="check" size={13} /></span></label>)}<button className="quiet clear-choice" disabled={!answers[q.number]} onClick={() => change('')}>Tanlovni tozalash</button></fieldset> : <div className="open-answer">{q.parts.length ? <><p className="muted">Har bir qismga alohida javob yozing.</p>{q.parts.map(part => <Field key={part.id} label={`${part.id}) ${part.prompt}`} placeholder="Javobingizni shu yerga yozing…" value={currentParts[part.id] || ''} onChange={value => change({ ...currentParts, [part.id]: value })} />)}</> : <Field label="Javobingiz" placeholder="Fikringizni aniq va to‘liq yozing…" rows={6} value={typeof currentAnswer === 'string' ? currentAnswer : ''} onChange={change} />}<span className="answer-hint"><Icon name="edit" size={14} />Javobingiz avtomatik saqlanadi.</span></div>}
      </section></div></div><footer className="sticky attempt-footer"><button className="secondary" disabled={index === 0} onClick={() => goTo(index - 1)}><Icon name="back" size={17} /><span>Oldingi</span></button><span className="footer-position">{index + 1} / {questions.length}</span>{index < questions.length - 1 ? <button onClick={() => goTo(index + 1)}>Keyingi savol<Icon name="arrow" size={17} /></button> : <button onClick={() => setReview(true)}>Yakuniy tekshiruv<Icon name="check" size={17} /></button>}</footer>
    </>}
  </>;
}

function StudentResult({ result, back }: { result: Submission; back(): void }) {
  const correct = result.answers.filter(a => a.correct === true).length;
  const pending = result.answers.filter(a => a.correct === null).length;
  const wrong = result.answers.length - correct - pending;
  return <>
    <section className="card result-hero"><span className="result-check"><Icon name="check" size={30} /></span><span className="eyebrow">{result.score === undefined ? 'JAVOBLAR TOPSHIRILDI' : 'YAKUNIY NATIJA'}</span><h2>{result.score === undefined ? 'Barakalla, test topshirildi!' : 'Mehnatingiz natijasi.'}</h2><p>{result.score === undefined ? 'Javoblaringiz qabul qilindi va saqlandi.' : 'O‘qituvchi testni yakunladi. Yakuniy natijangiz tayyor.'}</p>{result.score !== undefined && <div className="score-summary"><div><strong>{result.score}<small>ball</small></strong><span>To‘plangan ball</span></div><div><strong>{result.rank}<small>-o‘rin</small></strong><span>Reytingdagi o‘rningiz</span></div></div>}<div className="result-counts"><span><i className="result-dot correct" /><strong>{correct}</strong> to‘g‘ri</span><span><i className="result-dot incorrect" /><strong>{wrong}</strong> noto‘g‘ri</span>{pending > 0 && <span><i className="result-dot pending" /><strong>{pending}</strong> tekshirilmoqda</span>}</div></section>
    {result.score === undefined && <div className="result-waiting"><span className="stat-icon"><Icon name="clock" size={23} /></span><div><h3>Ball va o‘rin birozdan so‘ng.</h3><p>{pending ? 'Ochiq javoblar tekshirilmoqda. ' : ''}O‘qituvchi testni yakunlagach, ball va o‘rningiz shu yerda ko‘rinadi. Natija avtomatik yangilanadi.</p></div></div>}
    <section className="card"><div className="section-heading"><h2>Savollar bo‘yicha natija</h2><span className="muted">{result.answers.length} ta savol</span></div><div className="result-grid">{result.answers.map(answer => <div className={'result-cell ' + (answer.correct === null ? 'pending' : answer.correct ? 'correct' : 'incorrect')} key={answer.number} aria-label={`${answer.number}-savol: ${answer.correct === null ? 'tekshirilmoqda' : answer.correct ? 'to‘g‘ri' : 'noto‘g‘ri'}`}><strong>{String(answer.number).padStart(2, '0')}</strong><Icon name={answer.correct === null ? 'clock' : answer.correct ? 'check' : 'close'} size={16} /></div>)}</div><div className="result-legend"><span><i className="result-dot correct" />To‘g‘ri</span><span><i className="result-dot incorrect" />Noto‘g‘ri</span><span><i className="result-dot pending" />Tekshirilmoqda</span></div></section><div className="result-back"><button className="secondary" onClick={back}><Icon name="back" size={17} />Boshqa testga kirish</button></div>
  </>;
}

function TeacherResults({ id, back }: { id: number; back(): void }) {
  const confirm = useConfirmation();
  useTelegramBack(back);
  const [result, setResult] = useState<Results | null>(null);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [search, setSearch] = useState('');
  const [view, setView] = useState<'participants' | 'analysis'>('participants');
  const [copied, setCopied] = useState(false);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const answerDetail = useRef<HTMLElement>(null);
  const stackedResults = useMediaQuery('(max-width: 1250px)');
  useEffect(() => { if (selected && stackedResults) requestAnimationFrame(() => answerDetail.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })); }, [selected, stackedResults]);
  useEffect(() => () => clearTimeout(copyTimer.current), []);
  async function refresh() { try { setResult(await api<Results>(`/admin/tests/${id}/results`)); } catch (error) { setError(message(error)); } }
  useEffect(() => { void refresh(); const timer = setInterval(() => void refresh(), 5000); return () => clearInterval(timer); }, [id]);
  async function action(path: string, data: unknown = {}) {
    setBusy(true); setError('');
    try { await post(`/admin/tests/${id}/` + path, data); await refresh(); } catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  const pending = result?.answers.filter(a => a.grading_status !== 'done').length || 0;
  const participant = result?.submissions.find(s => s.id === selected);
  const participants = result?.submissions.filter(s => `${s.first_name} ${s.last_name || ''} ${s.user_id}`.toLocaleLowerCase().includes(search.toLocaleLowerCase())).sort((a, b) => result.test.status === 'finished' ? (a.rank || Infinity) - (b.rank || Infinity) : a.id - b.id) || [];
  async function copyCode() {
    try { await navigator.clipboard.writeText(result!.test.code); setCopied(true); clearTimeout(copyTimer.current); copyTimer.current = setTimeout(() => setCopied(false), 2500); }
    catch { setError('Kodni nusxalash uchun test kodi ustiga bosib ushlab turing.'); }
  }
  return <><button className="back-link" onClick={back}><Icon name="back" size={17} />O‘qituvchi kabineti</button>{error && <Alert>{error}</Alert>}{result ? <>
    <div className="page-heading"><div><div className="actions"><span className="eyebrow">TEST VA NATIJALAR</span><Badge status={result.test.status} /></div><h1>{result.test.title}</h1><p>Ishtirokchilar, javoblar va yakuniy hisobot — bir joyda.</p></div>{result.test.status === 'finished' && <a className="button" href={`/api/admin/tests/${id}/report`}><Icon name="download" size={18} />Excel hisobot</a>}</div>
    <section className="test-code-card"><span className="stat-icon"><Icon name="grid" size={24} /></span><div><span>O‘quvchilar uchun test kodi</span><strong>{result.test.code}</strong></div><button className="secondary" onClick={() => void copyCode()}><Icon name={copied ? 'check' : 'copy'} size={17} />{copied ? 'Nusxalandi' : 'Nusxalash'}</button></section>
    <div className="stats-grid"><div className="stat-card"><span className="stat-icon"><Icon name="users" /></span><div><span>Qatnashchilar</span><strong>{result.submissions.length}</strong></div></div><div className="stat-card"><span className="stat-icon pink"><Icon name="book" /></span><div><span>Jami savollar</span><strong>{result.test.total_questions}</strong></div></div><div className="stat-card"><span className="stat-icon amber"><Icon name="clock" /></span><div><span>Tekshirish kutilmoqda</span><strong>{pending}</strong></div></div></div>
    {result.test.status === 'active' && <section className="finish-panel"><div><h3>{pending ? 'Tekshiriladigan javoblar bor.' : 'Natijalarni e’lon qilishga tayyormisiz?'}</h3><p>{pending ? `${pending} ta javobni tekshiring yoki AI tekshiruvini qayta boshlang.` : 'Yakunlagach, yangi javoblar yopiladi va barcha ballar hisoblanadi.'}</p></div><div className="actions"><button className="secondary" disabled={busy} onClick={() => void action('retry-grading')}><Icon name="refresh" size={17} />Qayta tekshirish</button><button disabled={busy || pending > 0} onClick={async () => { if (await confirm({ title: 'Test yakunlansinmi?', description: 'Yangi javoblar qabul qilinmaydi. Savollar qiyinligi bo‘yicha ballar va o‘quvchilar reytingi hisoblanib, natijalar e’lon qilinadi.', action: 'Testni yakunlash' })) void action('finish'); }}>Testni yakunlash<Icon name="check" size={17} /></button></div></section>}
    <nav className="tabs results-tabs" aria-label="Natija bo‘limlari"><button className={view === 'participants' ? 'selected' : ''} aria-pressed={view === 'participants'} onClick={() => setView('participants')}><Icon name="users" size={17} />Qatnashchilar<span>{result.submissions.length}</span></button>{result.test.status === 'finished' && <button className={view === 'analysis' ? 'selected' : ''} aria-pressed={view === 'analysis'} onClick={() => setView('analysis')}><Icon name="chart" size={17} />Savollar tahlili</button>}</nav>
    {view === 'participants' ? <div className={'results-layout ' + (participant ? 'has-selection' : '')}><section className="card participants-card"><div className="section-heading"><h2>{result.test.status === 'finished' ? 'Yakuniy reyting' : 'Qatnashchilar'}</h2><span className="live-indicator"><span />Avtomatik yangilanadi</span></div><label className="search-field"><Icon name="search" size={17} /><input value={search} onChange={e => setSearch(e.target.value)} placeholder="O‘quvchini qidirish…" aria-label="Qatnashchilarni qidirish" /></label>{!participants.length ? <EmptyState icon="users" title={search ? 'O‘quvchi topilmadi' : 'Birinchi javobni kutamiz'}>{search ? 'Boshqa ism yoki ID bilan qidirib ko‘ring.' : 'Test kodini ulashing. Javob topshirgan o‘quvchilar shu yerda ko‘rinadi.'}</EmptyState> : <div className="participant-list">{participants.map(sub => <button className={'participant-row ' + (selected === sub.id ? 'participant-selected' : '')} key={sub.id} onClick={() => setSelected(sub.id)} aria-pressed={selected === sub.id}><span className="participant-avatar">{result.test.status === 'finished' ? sub.rank : sub.first_name.slice(0, 1).toUpperCase()}</span><span className="participant-name"><strong>{sub.first_name} {sub.last_name || ''}</strong><small>{result.answers.some(a => a.submission_id === sub.id && a.grading_status !== 'done') ? 'Javoblar tekshirilmoqda' : 'Javoblar tekshirilgan'}</small></span><span className="participant-score"><strong>{result.test.status === 'finished' ? sub.total_score : sub.total_correct}</strong><small>{result.test.status === 'finished' ? 'ball' : 'to‘g‘ri'}</small></span><Icon name="chevron" size={16} /></button>)}</div>}</section>
    {participant && <section ref={answerDetail} className="card answer-detail" aria-label="Tanlangan o‘quvchining javoblari"><div className="section-heading"><div><span className="eyebrow">O‘QUVCHI JAVOBLARI</span><h2>{participant.first_name} {participant.last_name || ''}</h2></div><button className="icon-button" aria-label="O‘quvchi javoblarini yopish" onClick={() => setSelected(null)}><Icon name="close" /></button></div><p className="muted">Telegram ID: {participant.user_id}</p>{result.answers.filter(a => a.submission_id === selected).map(answer => <article className="answer-review" key={answer.id}><div className="section-heading"><strong>{answer.question_num}-savol</strong><span className={'answer-status ' + (answer.grading_status !== 'done' ? 'pending' : answer.is_correct ? 'correct' : 'incorrect')}><Icon name={answer.grading_status !== 'done' ? 'clock' : answer.is_correct ? 'check' : 'close'} size={14} />{answer.grading_status !== 'done' ? 'Tekshirilmoqda' : answer.is_correct ? 'To‘g‘ri' : 'Noto‘g‘ri'}</span></div><p className="student-written-answer">{answer.user_answer || 'Javob berilmagan'}</p>{answer.ai_feedback && <p className="feedback-text">{answer.ai_feedback}</p>}{result.test.status === 'active' && <div className="override-actions"><button className="secondary" disabled={busy} aria-pressed={answer.grading_status === 'done' && Boolean(answer.is_correct)} onClick={() => void action('answers/' + answer.id, { correct: true, feedback: 'O‘qituvchi tasdiqladi.' })}><Icon name="check" size={16} />To‘g‘ri</button><button className="secondary" disabled={busy} aria-pressed={answer.grading_status === 'done' && !answer.is_correct} onClick={() => void action('answers/' + answer.id, { correct: false, feedback: 'O‘qituvchi tekshirdi.' })}><Icon name="close" size={16} />Noto‘g‘ri</button></div>}</article>)}</section>}</div> : <section className="card analysis-card"><div className="section-heading"><h2>Savollar bo‘yicha tahlil</h2><span className="muted">{result.questions.length} ta savol</span></div><p className="muted">Savollar to‘g‘ri javoblar soniga ko‘ra baholandi. Ko‘proq to‘g‘ri javob berilgan savollar osonroq hisoblanadi.</p>{result.questions.map(q => <div className="analysis-row" key={q.question_num}><strong>{q.question_num}-savol</strong><div><div className="analysis-bar"><span style={{ width: `${result.submissions.length ? q.correct_count / result.submissions.length * 100 : 0}%` }} /></div><small>{q.correct_count} / {result.submissions.length} to‘g‘ri</small></div><span className={'tier tier-' + q.assigned_tier}>{({ easy: 'Oson', medium: 'O‘rtacha', hard: 'Qiyin' } as Record<string, string>)[q.assigned_tier || ''] || 'Ochiq'}</span><strong>{q.assigned_points ?? '—'}<small> ball</small></strong></div>)}</section>}
  </> : <Loading label="Natijalar yuklanmoqda…" />}</>;
}

createRoot(document.getElementById('root')!).render(<App />);
