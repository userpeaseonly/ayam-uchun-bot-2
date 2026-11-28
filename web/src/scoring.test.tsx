import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { ScoringNotice, scoreUnit } from './scoring';

describe('Rasch result disclosure', () => {
  it('keeps historic scores in their original units', () => {
    expect(scoreUnit('legacy_tertile')).toBe('ball');
    expect(scoreUnit('rasch_v1')).toBe('T-ball');
    expect(renderToStaticMarkup(<ScoringNotice scoring={{ method: 'legacy_tertile' }} />)).toBe('');
  });
  it('does not describe unavailable scores as waiting for the teacher', () => {
    const html = renderToStaticMarkup(<ScoringNotice scoring={{ method: 'rasch_v1', status: 'unavailable', participants: 1, warnings: ['small_cohort', 'no_variation'] }} />);
    expect(html).toContain('ma’lumot yetarli emas');
    expect(html).toContain('To‘g‘ri javoblaringiz saqlandi');
    expect(html).not.toContain('Guruh o‘rtachasi 50');
    expect(html).not.toContain('yakunlangach');
  });
  it('labels estimated scores as practice and discloses small-cohort uncertainty', () => {
    const html = renderToStaticMarkup(<ScoringNotice scoring={{ method: 'rasch_v1', status: 'provisional', participants: 20, warnings: ['small_cohort', 'low_reliability'] }} />);
    expect(html).toContain('Rasmiy sertifikat bali emas');
    expect(html).toContain('20');
    expect(html).toContain('o‘lchash aniqligi past');
    expect(html).toContain('boshqa test yoki guruh');
  });
});
