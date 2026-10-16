import { describe, expect, it } from 'vitest';
import { isEmail, suggestEmail } from './email';

describe('email check', () => {
  it('accepts ordinary addresses', () => {
    for (const e of ['a@b.co', 'first.last+tag@mail.example.org', ' me@iiitd.ac.in ']) expect(isEmail(e)).toBe(true);
  });
  it('rejects the incomplete ones the browser lets through', () => {
    for (const e of ['aniket@gmail', 'aniket@gmail.', 'aniket@.com', '@gmail.com', 'a b@c.com', 'a@@b.com', 'a@b.c', '']) expect(isEmail(e)).toBe(false);
  });
  it('suggests a fix for a common domain slip, and only then', () => {
    expect(suggestEmail('x@gmial.com')).toBe('x@gmail.com');
    expect(suggestEmail('x@gmail.con')).toBe('x@gmail.com');
    expect(suggestEmail('x@gmail.com')).toBeNull();
    expect(suggestEmail('nonsense')).toBeNull();
  });
});
