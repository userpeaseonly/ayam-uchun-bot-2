import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, answered, questionAnswered, linkedImport, linkedTest } from './api';

afterEach(() => vi.unstubAllGlobals());

describe('readable request errors', () => {
  it('explains network failures without exposing browser errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    await expect(api('/me')).rejects.toMatchObject({ status: 0, message: 'Serverga ulanib bo‘lmadi. Internet aloqasini tekshirib, qayta urinib ko‘ring.' });
  });
  it('handles a proxy HTML error response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<h1>Bad gateway</h1>', { status: 502 })));
    await expect(api('/me')).rejects.toMatchObject({ status: 502, message: 'Serverdan javob olinmadi. Birozdan keyin qayta urinib ko‘ring.' });
  });
  it('preserves revision conflicts so drafts cannot overwrite newer answers', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({ error: 'Qoralama o‘zgargan.' }, { status: 409 })));
    await expect(api('/tests/T-1234/draft')).rejects.toMatchObject({ status: 409, message: 'Qoralama o‘zgargan.' });
  });
});

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


describe('session share links', () => {
  it('accepts opaque identifiers and Telegram start parameters', () => {
    const id = 'ab'.repeat(16);
    expect(linkedTest('?test=' + id)).toBe(id);
    expect(linkedTest('', 't_' + id)).toBe(id);
    expect(linkedTest('?test=' + id, 'T-1234')).toBe(id);
  });
  it('keeps legacy links working and rejects paths or arbitrary payloads', () => {
    expect(linkedTest('?test=123456')).toBe('T-123456');
    expect(linkedTest('?test=t-1234')).toBe('T-1234');
    expect(linkedTest('?test=../../admin')).toBeNull();
    expect(linkedTest('', 'import')).toBeNull();
    expect(linkedTest('', 't_' + 'a'.repeat(31))).toBeNull();
  });
});
