import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { api, post, questionAnswered, linkedImport, ApiError } from './api';
import type { Answers, ImportRecord, Passage, Question, Region, Results, StudentTest, Submission, TestDocument, TestSummary } from './types';
import './style.css';

const assetUrl = (id: string) => '/api/assets/' + id;
const message = (error: unknown) => error instanceof Error ? error.message : 'Amal bajarilmadi.';

// Only these formatting markers become elements; source HTML is never executed.
export function RichText({ text }: { text: string }) {
  const tokens = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*|<u>[\s\S]*?<\/u>)/g);
  return <span className="rich-text">{tokens.map((token, i) => token.startsWith('**') ? <strong key={i}>{token.slice(2, -2)}</strong> : token.startsWith('*') ? <em key={i}>{token.slice(1, -1)}</em> : token.startsWith('<u>') ? <u key={i}>{token.slice(3, -4)}</u> : <React.Fragment key={i}>{token}</React.Fragment>)}</span>;
}

function Field({ label, value, onChange, rows = 3 }: { label: string; value: string; onChange(value: string): void; rows?: number }) {
  return <label className="field">{label}<textarea rows={rows} value={value} onChange={e => onChange(e.target.value)} /></label>;
}

function App() {
  const [identity, setIdentity] = useState<{ is_admin: boolean; user: { first_name: string }; bot_import_url?: string | null } | null>(null);
  const [error, setError] = useState('');
  const [mode, setMode] = useState<'student' | 'teacher'>('student');
  useEffect(() => {
    const telegram = window.Telegram?.WebApp;
    telegram?.ready(); telegram?.expand();
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
  }, []);
  return <main>
    <header className="app-header"><div><span className="eyebrow">AYAM</span><h1>Testlar</h1></div>{identity && <span>{identity.user.first_name}</span>}</header>
    {!identity ? <section className="card"><h2>{error ? 'Telegram orqali oching' : 'Ulanmoqda…'}</h2><p>{error || 'Sessiya tekshirilmoqda.'}</p></section> : <>
      {identity.is_admin && <nav className="tabs"><button className={mode === 'student' ? 'selected' : ''} onClick={() => setMode('student')}>Test topshirish</button><button className={mode === 'teacher' ? 'selected' : ''} onClick={() => setMode('teacher')}>O‘qituvchi</button></nav>}
      {mode === 'teacher' && identity.is_admin ? <Teacher botImportUrl={identity.bot_import_url} /> : <Student />}
    </>}
  </main>;
}

function Teacher({ botImportUrl }: { botImportUrl?: string | null }) {
  const [imports, setImports] = useState<ImportRecord[]>([]);
  const [tests, setTests] = useState<TestSummary[]>([]);
  const [selectedImport, setSelectedImport] = useState<string | null>(() => linkedImport(location.search));
  const [selectedTest, setSelectedTest] = useState<number | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function refresh() {
    try {
      const [a, b] = await Promise.all([api<ImportRecord[]>('/admin/imports'), api<TestSummary[]>('/admin/tests')]);
      setImports(a); setTests(b);
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
  return <>
    <section className="card"><h2>Telegramdan test yuborish</h2><p>PDF yoki test rasmlarini botning shaxsiy chatiga yuboring yoki boshqa chatdan forward qiling. AI savollarni ajratadi, keyin shu yerda tekshirasiz.</p>
      <button onClick={() => {
        const telegram = window.Telegram?.WebApp;
        if (botImportUrl) {
          if (telegram?.openTelegramLink) telegram.openTelegramLink(botImportUrl);
          else { location.assign(botImportUrl); return; }
        }
        telegram?.close();
      }}>📎 Botga PDF yoki rasm yuborish</button>
      <p className="muted">Botda /import yuborishingiz ham mumkin. PDF darhol ajratiladi. Rasmlarni yuborib bo‘lgach, “Importni boshlash” tugmasini bosing yoki /done yozing.</p>
    </section>
    <section className="card"><details><summary>Telefondan fayl tanlash</summary><p>Fayl telefonda saqlangan bo‘lsa, shu yerdan yuklashingiz yoki bot chatiga biriktirishingiz mumkin.</p>
      <label className="field">PDF hujjat<input aria-label="PDF hujjat" type="file" accept=".pdf,application/pdf" disabled={busy} onChange={e => setFiles(Array.from(e.target.files || []))} /></label>
      <label className="field">Sahifa rasmlari<input aria-label="Sahifa rasmlari" type="file" accept="image/*" multiple disabled={busy} onChange={e => setFiles(Array.from(e.target.files || []))} /></label>
      {!!files.length && <ol>{files.map((file, i) => <li key={i}>{file.name}<button className="quiet" onClick={() => setFiles(list => list.filter((_, n) => n !== i))}>Olib tashlash</button>{i > 0 && <button className="quiet" onClick={() => setFiles(list => { const next = [...list]; [next[i - 1], next[i]] = [next[i], next[i - 1]]; return next; })}>↑</button>}</li>)}</ol>}
      <p className="muted">Bitta PDF yoki tartiblangan JPG/PNG/WebP rasmlar. Jami 20 MB, ko‘pi bilan 30 sahifa.</p><button disabled={!files.length || busy} onClick={() => void upload()}>{busy ? 'Yuklanmoqda…' : 'Yuklash va savollarni ajratish'}</button></details>
    </section>
    {error && <p className="error" role="alert">{error}</p>}
    <section className="card"><h2>Importlar</h2>{!imports.length && <p>Hali fayl yuklanmagan.</p>}{imports.map(item => <button className="list-row" key={item.id} onClick={() => setSelectedImport(item.id)}><span>{item.title}</span><small>{statusLabel(item.status)} · {item.progress}%</small></button>)}</section>
    <section className="card"><h2>Testlar va natijalar</h2>{tests.map(test => <button className="list-row" key={test.id} onClick={() => setSelectedTest(test.id)}><span>{test.code} · {test.title}</span><small>{statusLabel(test.status)}</small></button>)}</section>
  </>;
}

function statusLabel(status: string) {
  return ({ collecting: 'Rasmlar yig‘ilmoqda', queued: 'Navbatda', processing: 'Ajratilmoqda', failed: 'Xatolik', review: 'Tekshirish uchun tayyor', published: 'Nashr qilingan', active: 'Faol', finished: 'Yakunlangan' } as Record<string, string>)[status] || status;
}

function ImportEditor({ id, back, published }: { id: string; back(): void; published(id: number): void }) {
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
  return <>
    <button className="quiet" onClick={() => { if (!dirty || confirm('Saqlanmagan o‘zgarishlar bor. Chiqasizmi?')) back(); }}>← Importlar</button>
    {error && <p className="error" role="alert">{error}</p>}
    {notice && <p className="notice" role="status">{notice}</p>}
    {!record ? <p>Yuklanmoqda…</p> : record.status === 'published' ? <section className="card"><h2>Nashr qilingan</h2><button onClick={() => published(record.published_test_id!)}>Test va natijalar</button></section> : !document ? <section className="card"><h2>{statusLabel(record.status)}</h2><progress value={record.progress} max={100} />{record.status === 'collecting' ? <><p>{record.assets.filter(a => a.kind === 'source').length} ta rasm qabul qilindi. Qolgan sahifalarni bot chatiga yuboring. Hammasi qabul qilingach, importni boshlang.</p><button disabled={busy} onClick={async () => { setBusy(true); setError(''); try { await post('/admin/imports/' + id + '/start'); await load(); } catch (error) { setError(message(error)); } finally { setBusy(false); } }}>Importni boshlash</button></> : <p>{record.error || 'Savollar va rasmlar ajratilmoqda. Bu oynani yopishingiz mumkin.'}</p>}{record.status === 'failed' && <button onClick={() => void post('/admin/imports/' + id + '/retry').then(load).catch(e => setError(message(e)))}>Qayta urinish</button>}</section> : <fieldset className="editor-fields" disabled={busy}>
      <section className="card"><Field label="Test nomi" rows={1} value={document.title} onChange={title => change({ ...document, title })} />
        <p>{document.questions.length} ta savol · {document.questions.filter(q => q.kind === 'open').length} ta ochiq · {document.questions.filter(q => q.reviewed).length} ta tasdiqlangan</p>
        <details><summary>Import ogohlantirishlari ({document.warnings.length})</summary><ul>{document.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul></details>
        <details><summary>Javoblar kalitini birga kiritish</summary><Field label="Masalan: 1:A, 2:F, 3:B" value={keys} onChange={setKeys} /><button className="secondary" onClick={() => {
          const pairs = Array.from(keys.matchAll(/(\d{1,2})\s*[.\-:)]\s*([A-F])/gi));
          if (!pairs.length) { setError('Kalitlar topilmadi. 1:A, 2:F formatidan foydalaning.'); return; }
          const mapping = Object.fromEntries(pairs.map(p => [Number(p[1]), p[2].toUpperCase()]));
          change({ ...document, questions: document.questions.map(q => q.kind !== 'open' && mapping[q.number] ? { ...q, answer: mapping[q.number], reviewed: false } : q) });
          setNotice('Kalitlar kiritildi. Har bir savolni tekshirib tasdiqlang.');
        }}>Kalitlarni qo‘llash</button></details>
      </section>
      <nav className="tabs"><button className={tab === 'questions' ? 'selected' : ''} onClick={() => setTab('questions')}>Savollar</button><button className={tab === 'passages' ? 'selected' : ''} onClick={() => setTab('passages')}>Umumiy matnlar</button></nav>
      <div className="editor-layout"><div>
        {tab === 'questions' ? <section className="card">
          <div className="question-nav">{document.questions.map((q, i) => <button key={i} className={i === questionIndex ? 'selected' : q.reviewed ? 'complete' : 'secondary'} onClick={() => { setQuestionIndex(i); setVisiblePage(0); }}>{q.number}</button>)}</div>
          {q && <QuestionEditor key={questionIndex} question={q} passages={document.passages} pages={pages} update={updateQuestion} />}
          <div className="actions"><button className="secondary" onClick={() => { const number = Math.min(44, document.questions.length + 1); change({ ...document, questions: [...document.questions, newQuestion(number)] }); setQuestionIndex(document.questions.length); }}>Savol qo‘shish</button>{q && <button className="danger" onClick={() => { if (confirm('Savolni olib tashlaysizmi?')) { change({ ...document, questions: document.questions.filter((_, i) => i !== questionIndex) }); setQuestionIndex(0); } }}>Savolni o‘chirish</button>}</div>
        </section> : <section className="card">{document.passages.map((p, i) => <PassageEditor key={i} passage={p} pages={pages} update={next => change({ ...document, passages: document.passages.map((p, n) => i === n ? next : p), questions: document.questions.map(q => q.passage_id === p.id ? { ...q, reviewed: false } : q) })} remove={() => change({ ...document, passages: document.passages.filter((_, n) => n !== i) })} />)}<button onClick={() => change({ ...document, passages: [...document.passages, { id: 'p' + Date.now(), title: '', text: '', media: [], source_pages: [] }] })}>Matn qo‘shish</button></section>}
      </div><aside className="card source"><h3>Asl sahifa</h3><select aria-label="Asl sahifa" value={page?.page || ''} onChange={e => setVisiblePage(Number(e.target.value))}>{pages.map(p => <option key={p.id} value={p.page}>{p.page}-sahifa</option>)}</select>{page && <a href={assetUrl(page.id)} target="_blank" rel="noreferrer"><img src={assetUrl(page.id)} alt={`${page.page}-sahifa`} /></a>}<p className="muted">Kattalashtirish uchun rasmni bosing. Qasddan yozilgan imlo xatolarini o‘zgartirmang.</p></aside></div>
      <footer className="sticky actions"><span>{dirty ? 'Saqlanmagan o‘zgarishlar' : 'Saqlangan'}</span><button className="secondary" disabled={busy} onClick={() => void act()}>Saqlash</button><button disabled={busy} onClick={() => { if (confirm('Tasdiqlangan test nashr qilinadi. Shundan keyin savollar o‘zgarmaydi. Davom etasizmi?')) void act(true); }}>Nashr qilish</button></footer>
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
  const page = pages.find(p => p.page === pageNumber);
  function position(event: React.PointerEvent<HTMLDivElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    return { x: Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)), y: Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)) };
  }
  return <details><summary>Diagramma va rasm sohalari ({regions.length})</summary>
    <p className="muted">Sahifani tanlang va kerakli diagramma ustida to‘rtburchak chizing. Boshqa savol va javoblar sohaga tushmasin.</p>
    <select value={pageNumber} onChange={e => setPageNumber(Number(e.target.value))}>{pages.map(p => <option key={p.id} value={p.page}>{p.page}-sahifa</option>)}</select>
    {page && <div className="crop-canvas" onPointerDown={event => { event.currentTarget.setPointerCapture(event.pointerId); setStart(position(event)); }} onPointerUp={event => {
      if (!start) return; const end = position(event); const width = Math.abs(end.x - start.x), height = Math.abs(end.y - start.y);
      if (width > .01 && height > .01) update([...regions, { page: pageNumber, x: Math.min(start.x, end.x), y: Math.min(start.y, end.y), width, height, asset_id: '' }]);
      setStart(null);
    }}><img src={assetUrl(page.id)} alt="Rasm sohasini belgilang" draggable={false} />{regions.filter(r => r.page === pageNumber).map((r, i) => <div key={i} className="crop-box" style={{ left: `${r.x * 100}%`, top: `${r.y * 100}%`, width: `${r.width * 100}%`, height: `${r.height * 100}%` }} />)}</div>}
    {regions.map((r, i) => <div className="region-row" key={i}><span>{r.page}-sahifa</span>{(['x', 'y', 'width', 'height'] as const).map(key => <label key={key}>{key}<input type="number" min="0" max="1" step="0.01" value={Number(r[key].toFixed(3))} onChange={e => update(regions.map((region, n) => n === i ? { ...region, [key]: Number(e.target.value), asset_id: '' } : region))} /></label>)}<button className="quiet" onClick={() => update(regions.filter((_, n) => n !== i))}>×</button></div>)}
  </details>;
}

function QuestionEditor({ question: q, passages, pages, update }: { question: Question; passages: Passage[]; pages: PageAsset[]; update(q: Question): void }) {
  const patch = (value: Partial<Question>) => update({ ...q, ...value, reviewed: false });
  return <>
    <div className="row"><label>Savol raqami<input type="number" min="1" max="44" value={q.number} onChange={e => patch({ number: Number(e.target.value) })} /></label><label>Turi<select value={q.kind} onChange={e => { const kind = e.target.value as Question['kind']; patch({ kind, options: kind === 'open' ? [] : q.options.length ? q.options : [{ label: 'A', text: '' }, { label: 'B', text: '' }], parts: kind === 'open' ? q.parts : [], answer: '' }); }}><option value="choice">Variantli</option><option value="matching">Moslashtirish</option><option value="open">Ochiq</option></select></label></div>
    {!!q.warnings.length && <p className="warning">{q.warnings.join('\n')}</p>}
    <Field label="Savol matni · **qalin**, *kursiv*, <u>tagiga chizish</u>" value={q.text} onChange={text => patch({ text })} />
    <details><summary>Matn ko‘rinishi</summary><RichText text={q.text} /></details>
    <label className="field">Umumiy matn<select value={q.passage_id || ''} onChange={e => patch({ passage_id: e.target.value || null })}><option value="">Alohida savol</option>{passages.map(p => <option key={p.id} value={p.id}>{p.title || p.id}</option>)}</select></label>
    {q.kind !== 'open' ? <>
      {q.options.map((option, index) => <div className="option-editor" key={index}><b>{option.label}</b><textarea rows={2} value={option.text} onChange={e => patch({ options: q.options.map((o, i) => i === index ? { ...o, text: e.target.value } : o) })} /><button className="quiet" onClick={() => patch({ options: q.options.filter((_, i) => i !== index) })}>×</button></div>)}
      <button className="secondary" disabled={q.options.length >= 6} onClick={() => { const label = 'ABCDEF'.split('').find(label => !q.options.some(o => o.label === label))!; patch({ options: [...q.options, { label, text: '' }] }); }}>Variant qo‘shish</button>
      <label className="field">To‘g‘ri javob<select value={q.answer} onChange={e => patch({ answer: e.target.value })}><option value="">Tanlang</option>{q.options.map(o => <option key={o.label}>{o.label}</option>)}</select></label>
    </> : <>
      {q.parts.map((part, index) => <div className="option-editor" key={part.id}><b>{part.id})</b><textarea value={part.prompt} onChange={e => patch({ parts: q.parts.map((p, i) => i === index ? { ...p, prompt: e.target.value } : p) })} /><button className="quiet" onClick={() => patch({ parts: q.parts.filter((_, i) => i !== index) })}>×</button></div>)}
      <button className="secondary" disabled={q.parts.length >= 6} onClick={() => patch({ parts: [...q.parts, { id: 'abcdef'.split('').find(id => !q.parts.some(p => p.id === id))!, prompt: '' }] })}>a/b qism qo‘shish</button>
      <Field label="O‘qituvchi tasdiqlagan javob va tekshirish mezoni" rows={5} value={q.rubric} onChange={rubric => patch({ rubric })} />
      {!q.parts.length && <Field label="Aniq qabul qilinadigan javoblar · har biri yangi qatorda" value={q.accepted_answers.join('\n')} onChange={value => patch({ accepted_answers: value.split('\n') })} />}
      <label className="field">Savol uchun ball<input type="number" min="0.1" max="100" step="0.1" value={q.points} onChange={e => patch({ points: Number(e.target.value) })} /></label>
      {!!q.parts.length && <p className="muted">Barcha qismlar to‘g‘ri bo‘lsa, bu bitta savol uchun {q.points} ball beriladi.</p>}
    </>}
    <RegionEditor regions={q.media} pages={pages} update={media => patch({ media })} />
    <label className="check"><input type="checkbox" checked={q.reviewed} onChange={e => update({ ...q, reviewed: e.target.checked })} />Asl savol, matnlar, rasm va to‘g‘ri javob mezonini tekshirdim.</label>
  </>;
}

function PassageEditor({ passage: p, pages, update, remove }: { passage: Passage; pages: PageAsset[]; update(p: Passage): void; remove(): void }) {
  return <article className="passage-editor"><p className="eyebrow">{p.id}</p><Field label="Matn sarlavhasi" value={p.title} rows={1} onChange={title => update({ ...p, title })} /><Field label="Umumiy matn, izohlar va lug‘at" value={p.text} rows={12} onChange={text => update({ ...p, text })} /><RegionEditor regions={p.media} pages={pages} update={media => update({ ...p, media })} /><button className="danger" onClick={() => { if (confirm('Umumiy matnni o‘chirasizmi? Bog‘langan savollarni tekshiring.')) remove(); }}>Matnni o‘chirish</button></article>;
}

function Student() {
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
  if (test) return <Attempt key={test.id} initial={test} back={() => setTest(null)} />;
  return <section className="card join"><span className="eyebrow">BILIMINGIZNI SINANG</span><h2>Testga kirish</h2><p>O‘qituvchingiz bergan kodni kiriting.</p><form onSubmit={e => { e.preventDefault(); void join(); }}><label>Test kodi<input value={code} onChange={e => setCode(e.target.value)} placeholder="T-123456" autoCapitalize="characters" required /></label><button disabled={busy}>{busy ? 'Ochilyapti…' : 'Testni ochish →'}</button></form>{error && <p className="error" role="alert">{error}</p>}</section>;
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
  const latest = useRef(answers);
  const saved = useRef(JSON.stringify(initial.draft));
  const saving = useRef<Promise<void> | null>(null);
  const conflict = useRef(false);
  const questions = initial.document.questions;
  const q = questions[index];
  async function flush() {
    while (saving.current) await saving.current;
    const serialized = JSON.stringify(latest.current);
    if (serialized === saved.current || result) return;
    if (conflict.current) throw new Error('Javoblar boshqa oynada o‘zgargan. Qayta ochishdan oldin javoblaringizni nusxalang.');
    const task = (async () => {
      setSaveState('Saqlanmoqda…');
      try {
        const value = await post<{ revision: number }>('/tests/' + initial.code + '/draft', { answers: JSON.parse(serialized), revision: revision.current });
        revision.current = value.revision; saved.current = serialized; setSaveState('Saqlangan');
      } catch (error) { if (error instanceof ApiError && error.status === 409) conflict.current = true; setSaveState('Saqlanmadi · qayta uriniladi'); throw error; }
    })();
    saving.current = task;
    try { await task; } finally { saving.current = null; }
  }
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
  function answerPreview(value: string | Record<string, string> | undefined) { return typeof value === 'object' ? Object.entries(value).map(([k, v]) => `${k}) ${v}`).join('\n') : value || 'Javob yo‘q'; }
  return <>
    <button className="quiet" onClick={() => { if (result) back(); else void flush().then(back).catch(error => setError(message(error))); }}>← Testlar</button>
    <section className="card compact"><span className="eyebrow">{initial.code}</span><h2>{initial.document.title}</h2><p>{result ? 'Topshirilgan' : `${count} / ${questions.length} javob berilgan · ${saveState}`}</p></section>
    {error && <p className="error" role="alert">{error}</p>}
    {result ? <section className="card"><h2>Javoblaringiz qabul qilindi</h2><div className="result-grid">{result.answers.map(answer => <span key={answer.number}>{answer.number}. {answer.correct === null ? '⏳' : answer.correct ? '✅' : '❌'}</span>)}</div>{result.score === undefined ? <p>Ochiq savollar tekshirilishi mumkin. Ball va o‘rningiz o‘qituvchi testni yakunlagach ko‘rinadi.</p> : <div className="score"><strong>{result.score} ball</strong><span>{result.rank}-o‘rin · {result.total_correct} ta to‘g‘ri javob</span></div>}</section> : initial.status !== 'active' ? <section className="card"><h2>Test yakunlangan</h2><p>Yangi javoblar qabul qilinmaydi.</p></section> : review ? <section className="card"><h2>Yuborishdan oldin tekshiring</h2><p>{questions.length - count} ta savol to‘liq javobsiz. Bo‘sh javoblar noto‘g‘ri hisoblanadi. Tasdiqlangach, javoblarni o‘zgartirib bo‘lmaydi.</p>{questions.map((q, i) => <button className="list-row" key={q.number} onClick={() => { setIndex(i); setReview(false); }}><b>{q.number}-savol</b><span>{answerPreview(answers[q.number])}</span></button>)}<div className="actions"><button className="secondary" onClick={() => setReview(false)}>Qaytish</button><button disabled={busy} onClick={() => void submit()}>{busy ? 'Saqlanmoqda…' : 'Tasdiqlash va topshirish'}</button></div></section> : q && <>
      <nav className="question-nav">{questions.map((question, i) => <button key={question.number} className={i === index ? 'selected' : questionAnswered(question.parts, answers[question.number]) ? 'complete' : 'secondary'} onClick={() => setIndex(i)}>{question.number}</button>)}</nav>
      {passage && <details className="card passage" open><summary>{passage.title || 'Savol uchun umumiy matn'}</summary><RichText text={passage.text} />{passage.media.map(id => <img className="question-image" key={id} src={assetUrl(id)} alt="Matnga tegishli rasm" />)}</details>}
      <section className="card"><span className="eyebrow">{q.number}-SAVOL · {q.kind === 'open' ? 'OCHIQ JAVOB' : q.kind === 'matching' ? 'MOSLASHTIRISH' : 'VARIANTLI'}</span><h3><RichText text={q.text} /></h3>{q.media.map(id => <img className="question-image" key={id} src={assetUrl(id)} alt="Savol diagrammasi" />)}
        {q.kind !== 'open' ? <fieldset className="choices"><legend>Javobni tanlang</legend>{q.options.map(option => <label className={answers[q.number] === option.label ? 'chosen' : ''} key={option.label}><input type="radio" name={'q' + q.number} checked={answers[q.number] === option.label} onChange={() => change(option.label)} /><b>{option.label}</b><RichText text={option.text} /></label>)}<button className="quiet" onClick={() => change('')}>Tanlovni tozalash</button></fieldset> : q.parts.length ? q.parts.map(part => <Field key={part.id} label={`${part.id}) ${part.prompt}`} value={currentParts[part.id] || ''} onChange={value => change({ ...currentParts, [part.id]: value })} />) : <Field label="Javobingiz" rows={5} value={typeof currentAnswer === 'string' ? currentAnswer : ''} onChange={change} />}
      </section><footer className="sticky actions"><button className="secondary" disabled={index === 0} onClick={() => setIndex(i => i - 1)}>← Oldingi</button>{index < questions.length - 1 && <button className="secondary" onClick={() => setIndex(i => i + 1)}>Keyingi →</button>}<button onClick={() => setReview(true)}>Tekshirish va yuborish</button></footer>
    </>}
  </>;
}

function TeacherResults({ id, back }: { id: number; back(): void }) {
  const [result, setResult] = useState<Results | null>(null);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  async function refresh() { try { setResult(await api<Results>(`/admin/tests/${id}/results`)); } catch (error) { setError(message(error)); } }
  useEffect(() => { void refresh(); const timer = setInterval(() => void refresh(), 5000); return () => clearInterval(timer); }, [id]);
  async function action(path: string, data: unknown = {}) {
    setBusy(true); setError('');
    try { await post(`/admin/tests/${id}/` + path, data); await refresh(); } catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  return <><button className="quiet" onClick={back}>← Testlar</button>{error && <p className="error" role="alert">{error}</p>}{result ? <>
    <section className="card"><span className="eyebrow">{result.test.code} · {statusLabel(result.test.status)}</span><h2>{result.test.title}</h2><p>{result.submissions.length} ta topshiriq · {result.answers.filter(a => a.grading_status !== 'done').length} ta javob tekshirishni kutmoqda</p><p>O‘quvchilarga kod: <strong>{result.test.code}</strong></p><div className="actions">{result.test.status === 'active' ? <><button disabled={busy} onClick={() => { if (confirm('Testni yakunlaysizmi? Yangi javoblar yopiladi va ballar hisoblanadi.')) void action('finish'); }}>Testni yakunlash</button><button className="secondary" disabled={busy} onClick={() => void action('retry-grading')}>AI tekshiruvini qayta urinish</button></> : <a className="button" href={`/api/admin/tests/${id}/report`}>Excel hisobot</a>}</div></section>
    <section className="card"><h2>Qatnashchilar</h2>{!result.submissions.length && <p>Hali javob topshirilmagan.</p>}{result.submissions.map(sub => <button className="list-row" key={sub.id} onClick={() => setSelected(sub.id)}><span>{sub.first_name} {sub.last_name || ''} <small>#{sub.user_id}</small></span><b>{result.test.status === 'finished' ? `${sub.rank}-o‘rin · ${sub.total_score} ball` : `${sub.total_correct} ta to‘g‘ri`}</b></button>)}</section>
    {selected && <section className="card"><h2>O‘quvchi javoblari</h2>{result.answers.filter(a => a.submission_id === selected).map(answer => <article className="answer-review" key={answer.id}><b>{answer.question_num}. {answer.grading_status !== 'done' ? '⏳ Tekshirilmoqda' : answer.is_correct ? '✅' : '❌'}</b><p className="rich-text">{answer.user_answer || 'Javob berilmagan'}</p><p className="muted">{answer.ai_feedback}</p>{result.test.status === 'active' && <div className="actions"><button className="secondary" disabled={busy} onClick={() => void action('answers/' + answer.id, { correct: true, feedback: 'O‘qituvchi tasdiqladi.' })}>To‘g‘ri</button><button className="secondary" disabled={busy} onClick={() => void action('answers/' + answer.id, { correct: false, feedback: 'O‘qituvchi tekshirdi.' })}>Noto‘g‘ri</button></div>}</article>)}</section>}
    {result.test.status === 'finished' && <section className="card"><h2>Savollar tahlili</h2>{result.questions.map(q => <p key={q.question_num}>{q.question_num}. {q.correct_count} ta to‘g‘ri · {q.assigned_tier} · {q.assigned_points} ball</p>)}</section>}
  </> : <p>Yuklanmoqda…</p>}</>;
}

createRoot(document.getElementById('root')!).render(<App />);
