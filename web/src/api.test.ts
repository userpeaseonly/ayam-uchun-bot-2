import { describe, expect, it } from 'vitest';
import { answered, questionAnswered, linkedImport } from './api';

describe('submission completeness', () => {
  it('requires every supplied subpart to contain text', () => {
    expect(answered({ a: 'suv', b: '' })).toBe(false);
    expect(answered({ a: 'suv', b: 'havo' })).toBe(true);
    expect(answered({})).toBe(false);
    expect(answered('  ')).toBe(false);
    expect(answered('F')).toBe(true);
  });
  it('counts missing a/b fields as incomplete', () => {
    expect(questionAnswered([{ id: 'a' }, { id: 'b' }], { a: 'suv' })).toBe(false);
    expect(questionAnswered([{ id: 'a' }, { id: 'b' }], { a: 'suv', b: 'havo' })).toBe(true);
  });
});

describe('Telegram import links', () => {
  it('opens only a valid import identifier from the bot button', () => {
    expect(linkedImport('?import=' + 'a'.repeat(32))).toBe('a'.repeat(32));
    expect(linkedImport('?import=../../other-user')).toBeNull();
    expect(linkedImport('?test=T-1234')).toBeNull();
  });
});
