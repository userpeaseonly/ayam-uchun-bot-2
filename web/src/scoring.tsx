import type { Scoring } from './types';

export function scoreUnit(method?: Scoring['method']) {
  return method === 'rasch_v1' ? 'T-ball' : 'ball';
}

export function ScoringNotice({ scoring }: { scoring?: Scoring }) {
  if (scoring?.method !== 'rasch_v1') return null;
  if (scoring.status === 'pending') return <p className="muted">Rash modeli bo‘yicha mashq natijasi test yakunlangach hisoblanadi.</p>;
  const unavailable = scoring.status === 'unavailable';
  const warnings = scoring.warnings || [];
  return <section className="card scoring-note" aria-label="Natijani baholash haqida">
    <strong>{unavailable ? 'Rash bahosi uchun ma’lumot yetarli emas' : 'Rash modeli · mashq natijasi'}</strong>
    <p>{unavailable ? 'To‘g‘ri javoblaringiz saqlandi. Bu guruh uchun ishonchli ball va o‘rin hisoblab bo‘lmadi.' : 'Guruhingizga nisbiy taxmin. Rasmiy sertifikat bali emas.'}</p>
    <details className="scoring-help"><summary>Natijani qanday tushunish kerak?</summary>
      {!unavailable && <p>Guruh o‘rtachasi 50 T-ball. Natijani boshqa test yoki guruh bali bilan bevosita solishtirmang.</p>}
      {warnings.includes('small_cohort') && <p>Qatnashchilar kam ({scoring.participants} nafar). Taxmin o‘zgaruvchan bo‘lishi mumkin.</p>}
      {warnings.includes('short_test') && <p>Baholash uchun savollar kam. Natijada noaniqlik yuqoriroq.</p>}
      {warnings.includes('extreme_items') && <p>Hamma to‘g‘ri yoki hamma noto‘g‘ri javob bergan savollar qiyinligini aniqlab bo‘lmaydi. Ular to‘g‘ri javoblar sonida saqlanadi.</p>}
      {warnings.includes('low_reliability') && <p>Ushbu natijaning o‘lchash aniqligi past. Uni yakuniy bilim darajasi deb qabul qilmang.</p>}
      {warnings.includes('item_misfit') && <p>Ayrim savollar statistik tekshiruvga muhtoj.</p>}
      {warnings.includes('nonconvergence') && <p>Hisoblash barqaror yechimga kelmadi. Ball ko‘rsatilmagan.</p>}
    </details>
  </section>;
}
