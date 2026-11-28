import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { RichText } from './rich-text';

describe('shared exam and practice text rendering', () => {
  it('renders supported formatting without executing uploaded HTML', () => {
    const html = renderToStaticMarkup(<RichText text={'**Otlar** *mashqi* <u>muhim</u> <img src=x onerror=alert(1) />'} />);
    expect(html).toContain('<strong>Otlar</strong>');
    expect(html).toContain('<em>mashqi</em>');
    expect(html).toContain('<u>muhim</u>');
    expect(html).not.toContain('<img');
    expect(html).toContain('&lt;img');
  });
});
