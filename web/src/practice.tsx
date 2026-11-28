import { useEffect, useRef, useState } from 'react';
import { api, post, questionAnswered } from './api';
import type { StudentQuestion, StudentTest } from './types';
import { Alert, EmptyState, Icon, Loading, PageHeading, useExitGuard, useTelegramBack } from './ui';
import { RichText } from './rich-text';
import { ExplanationPlayer } from './voice-explanation';
import { ProtectedTest } from './content-protection';
import './practice.css';

type Answer = string | Record<string, string>;
type Grid = { max_number: number; numbers: { number: number; total: number; checked: number; correct: number }[]; resume_number: number | null };
type PracticeItem = {
  id: number; number: number; source_title: string; publisher_name: string;
  question: StudentQuestion; passage: StudentTest['document']['passages'][number] | null;
  answer: Answer; revision: number; total: number; position: number; previous_id: number | null; next_id: number | null;
  check: { id: number; status: 'done' | 'pending' | 'failed'; answer: Answer; correct: boolean | null; feedback: string | null } | null;
  solution?: { answer: string; accepted_answers: string[]; rubric: string; audio_url: string | null };
};
const errorMessage = (error: unknown) => error instanceof Error ? error.message : 'Amal bajarilmadi.';

export function Practice({ back, onFocus }: { back(): void; onFocus(value: boolean): void }) {
  const [grid, setGrid] = useState<Grid | null>(null);
  const [item, setItem] = useState<PracticeItem | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { void refresh(); }, []);
  useEffect(() => { onFocus(Boolean(item)); return () => onFocus(false); }, [Boolean(item), onFocus]);
  useEffect(() => { window.scrollTo({ top: 0 }); }, [item?.id]);
  async function refresh() {
    try { setGrid(await api<Grid>('/practice/grid')); setError(''); }
    catch (error) { setError(errorMessage(error)); }
  }
  async function open(number: number, id?: number) {
    setBusy(true); setError('');
    try { setItem(await post<PracticeItem>(`/practice/numbers/${number}/open`, { item_id: id })); }
    catch (error) { setError(errorMessage(error)); }
    finally { setBusy(false); }
  }
  if (item) return <ProtectedTest>{error && <Alert>{error}</Alert>}<PracticeQuestion key={item.id} initial={item} busy={busy} move={id => open(item.number, id)} back={() => { setItem(null); void refresh(); }} /></ProtectedTest>;
  return <div className="practice-home">
    <button className="back-link" onClick={back}><Icon name="back" size={17} />Testlar</button>
    <PageHeading icon="grid" title="Mavzulashtirilgan" hint="Basirat · Imtihon savollari bo‘yicha mashq" />
    <p className="muted">Savol raqamini tanlang. Vaqt cheklanmagan.</p>
    {error && <Alert>{error}<button className="quiet" onClick={() => void refresh()}>Qayta urinish</button></Alert>}
    {busy ? <Loading label="Savol ochilmoqda…" /> : !grid ? !error && <Loading label="Mashqlar yuklanmoqda…" /> : !grid.max_number ? <section className="card"><EmptyState icon="book" title="Mashqlar tez orada">Basirat ustozlari savollarni tayyorlamoqda.</EmptyState></section> : <>
      {grid.resume_number != null && <button className="practice-resume secondary" onClick={() => void open(grid.resume_number!)}><Icon name="refresh" size={18} />{grid.resume_number}-savolni davom ettirish<Icon name="arrow" size={17} /></button>}
      <section className="card practice-grid-card"><nav className="question-nav practice-number-grid" aria-label="Mashq uchun imtihon savoli raqami">{Array.from({ length: grid.max_number }, (_, i) => {
        const number = i + 1; const bucket = grid.numbers.find(b => b.number === number);
        return <button key={number} disabled={!bucket?.total} className={bucket && bucket.checked === bucket.total ? 'complete' : 'secondary'} aria-label={`${number}-savol, ${bucket?.total || 0} ta mashq, ${bucket?.checked || 0} ta tekshirilgan`} onClick={() => void open(number)}><strong>{number}</strong><small>{bucket?.total || 0} ta</small></button>;
      })}</nav></section>
    </>}
  </div>;
}

function PracticeQuestion({ initial, busy, move, back }: { initial: PracticeItem; busy: boolean; move(id: number): Promise<void>; back(): void }) {
  const [data, setData] = useState(initial);
  const [answer, setAnswer] = useState<Answer>(initial.answer);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [checking, setChecking] = useState(false);
  const draft = useRef(initial.answer);
  const revision = useRef(initial.revision);
  const dirty = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const queue = useRef<Promise<void>>(Promise.resolve());
  const key = useRef<string | null>(null);
  const q = data.question;
  const pending = data.check?.status === 'pending' || data.check?.status === 'failed';
  const media = (id: string) => `/api/practice/items/${data.id}/assets/${id}`;
  async function flush() {
    clearTimeout(timer.current);
    const task = queue.current.catch(() => {}).then(async () => {
      while (dirty.current) {
        dirty.current = false; setSaving(true);
        try {
          const result = await api<{ revision: number }>(`/practice/items/${data.id}`, { method: 'PUT', body: JSON.stringify({ answer: draft.current, revision: revision.current }) });
          revision.current = result.revision;
        } catch (error) { dirty.current = true; throw error; }
        finally { setSaving(false); }
      }
    });
    queue.current = task;
    return task;
  }
  useExitGuard(flush);
  async function leave(id?: number) {
    try { await flush(); if (id == null) back(); else await move(id); }
    catch (error) { setError(errorMessage(error)); }
  }
  useTelegramBack(() => { void leave(); });
  useEffect(() => () => clearTimeout(timer.current), []);
  useEffect(() => {
    if (data.check?.status !== 'pending') return;
    let active = true;
    const poll = setInterval(() => {
      void api<PracticeItem>(`/practice/items/${data.id}`).then(value => { if (active) { setData(value); setError(''); } }).catch(error => { if (active) setError(errorMessage(error)); });
    }, 2500);
    return () => { active = false; clearInterval(poll); };
  }, [data.id, data.check?.status]);
  function change(value: Answer) {
    draft.current = value; setAnswer(value); dirty.current = true; key.current = null; setError('');
    clearTimeout(timer.current);
    timer.current = setTimeout(() => { void flush().catch(error => setError(errorMessage(error))); }, 500);
  }
  async function check() {
    setChecking(true); setError('');
    try {
      await flush();
      key.current ||= crypto.randomUUID().replaceAll('-', '');
      const result = await post<PracticeItem>(`/practice/items/${data.id}/check`, { answer: draft.current, revision: revision.current, request_key: key.current });
      revision.current = result.revision; setData(result); key.current = null;
    } catch (error) { setError(errorMessage(error)); }
    finally { setChecking(false); }
  }
  async function repeat() {
    setChecking(true);
    try {
      change(q.parts.length ? Object.fromEntries(q.parts.map(p => [p.id, ''])) : '');
      await flush(); setData(previous => ({ ...previous, check: null, solution: undefined }));
    } catch (error) { setError(errorMessage(error)); }
    finally { setChecking(false); }
  }
  async function reloadSaved() {
    clearTimeout(timer.current); setChecking(true);
    try {
      await queue.current.catch(() => {});
      const latest = await api<PracticeItem>(`/practice/items/${data.id}`);
      draft.current = latest.answer; revision.current = latest.revision; dirty.current = false;
      key.current = null; setAnswer(latest.answer); setData(latest); setError('');
    } catch (error) { setError(errorMessage(error)); }
    finally { setChecking(false); }
  }
  const locked = busy || checking || Boolean(data.check);
  return <div className="practice-attempt">
    <button className="back-link" disabled={busy || checking} onClick={() => void leave()}><Icon name="back" size={17} />Raqamlarga qaytish</button>
    <div className="section-heading"><div><span className="eyebrow">MAVZULASHTIRILGAN</span><h1>{data.number}-savol</h1></div><span className="save-state">{saving ? 'Saqlanmoqda…' : dirty.current ? 'Saqlash kutilmoqda' : 'Saqlandi'}</span></div>
    <p className="muted practice-source">{data.source_title} · {data.publisher_name}</p>
    {error && <Alert>{error}<button className="quiet" disabled={checking} onClick={() => void flush().catch(error => setError(errorMessage(error)))}>Saqlashni qayta urinish</button><button className="quiet" disabled={checking} onClick={() => void reloadSaved()}>Saqlangan javobni yuklash</button></Alert>}
    {data.passage && <details className="card passage" open><summary>{data.passage.title || 'Savol uchun umumiy matn'}</summary><div className="passage-content"><RichText text={data.passage.text} />{data.passage.media.map(id => <img className="question-image" key={id} src={media(id)} alt="Matnga tegishli rasm" />)}</div></details>}
    <section className="card question-card"><div className="section-heading"><span className="question-kind">{q.kind === 'open' ? 'Ochiq javob' : 'Variantli savol'}</span><span className="muted">{data.position} / {data.total} mashq</span></div><h2 className="question-text"><RichText text={q.text} /></h2>{q.media.map(id => <img className="question-image" key={id} src={media(id)} alt="Savol rasmi" />)}
      <fieldset className="editor-fields" disabled={locked}>{q.kind !== 'open' ? <fieldset className="choices"><legend>Bitta javobni tanlang</legend>{q.options.map(option => <label className={(answer === option.label ? 'chosen ' : '') + (data.check && data.solution?.answer === option.label ? 'practice-option-correct' : '')} key={option.label}><input type="radio" name={`practice-${data.id}`} checked={answer === option.label} onChange={() => change(option.label)} /><span className="choice-letter">{option.label}</span><RichText text={option.text} /></label>)}</fieldset> : <div className="open-answer">{q.parts.length ? q.parts.map(part => <label className="field" key={part.id}>{part.id}) {part.prompt}<textarea value={typeof answer === 'object' ? answer[part.id] || '' : ''} onChange={e => change({ ...(typeof answer === 'object' ? answer : {}), [part.id]: e.target.value })} /></label>) : <label className="field">Javobingiz<textarea rows={4} value={typeof answer === 'string' ? answer : ''} onChange={e => change(e.target.value)} /></label>}</div>}</fieldset>
      {!data.check && <button className="submit-test full-width" disabled={checking || busy || !questionAnswered(q.parts, answer)} onClick={() => void check()}>{checking ? 'Tekshirilmoqda…' : 'Javobni tekshirish'}<Icon name="check" size={17} /></button>}
    </section>
    {data.check && <section className={'card practice-feedback ' + (data.check.correct ? 'practice-correct' : '')} aria-live="polite"><h2>{pending ? data.check.status === 'failed' ? 'Tekshirish vaqtincha ishlamadi' : 'Javobingiz tekshirilmoqda' : data.check.correct ? 'To‘g‘ri javob!' : 'Yana bir bor o‘rganamiz'}</h2>
      {data.check.feedback && <p>{data.check.feedback}</p>}
      {data.solution?.answer && <p><strong>To‘g‘ri javob: {data.solution.answer}</strong> · {q.options.find(o => o.label === data.solution?.answer)?.text}</p>}
      {!!data.solution?.accepted_answers.length && <p><strong>Qabul qilinadigan javob:</strong> {data.solution.accepted_answers.join(' · ')}</p>}
      {data.solution?.rubric && <details><summary>Javob mezoni</summary><p><RichText text={data.solution.rubric} /></p></details>}
      {data.solution?.audio_url && <ExplanationPlayer url={data.solution.audio_url} number={data.number} />}
      {data.check.status === 'failed' && <button className="secondary" disabled={checking} onClick={async () => { setChecking(true); try { setData(await post<PracticeItem>(`/practice/items/${data.id}/retry`)); setError(''); } catch (error) { setError(errorMessage(error)); } finally { setChecking(false); } }}>Tekshirishni qayta urinish</button>}
      {!pending && <button className="secondary" disabled={checking} onClick={() => void repeat()}><Icon name="refresh" size={16} />Qayta ishlash</button>}
    </section>}
    <footer className="sticky attempt-footer"><button className="secondary" disabled={busy || checking || data.previous_id == null} onClick={() => void leave(data.previous_id!)}><Icon name="back" size={17} />Oldingi</button><span className="footer-position">{data.position} / {data.total}</span>{data.next_id != null ? <button disabled={busy || checking} onClick={() => void leave(data.next_id!)}>Keyingi<Icon name="arrow" size={17} /></button> : <button disabled={busy || checking} onClick={() => void leave()}>Raqamlar<Icon name="grid" size={17} /></button>}</footer>
  </div>;
}

export function PracticePublication({ testId }: { testId: number }) {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { void api<{ enabled: boolean }>(`/teacher/tests/${testId}/practice`).then(value => setEnabled(value.enabled)).catch(error => setError(errorMessage(error))); }, [testId]);
  return <details className="card practice-publication"><summary><Icon name="grid" size={18} />Mavzulashtirilgan</summary><p>Bu test savollari asl raqamiga ko‘ra umumiy Basirat mashqlariga qo‘shiladi. Javoblar, ochiq savol mezonlari va ovozli izohlar o‘quvchi tekshirishni bosgach ochiladi.</p>{error && <Alert>{error}</Alert>}<label className="check"><input type="checkbox" disabled={busy || enabled == null} checked={enabled || false} onChange={async e => { const value = e.target.checked; setBusy(true); setError(''); try { const result = await api<{ enabled: boolean }>(`/teacher/tests/${testId}/practice`, { method: 'PUT', body: JSON.stringify({ enabled: value }) }); setEnabled(result.enabled); } catch (error) { setError(errorMessage(error)); } finally { setBusy(false); } }} /><span>{busy ? 'Saqlanmoqda…' : 'Basirat mashqlarida ko‘rsatish'}</span></label></details>;
}
