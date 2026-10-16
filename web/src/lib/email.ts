/** Same shape the server accepts for local accounts: one @, a dot inside the domain, a 2+ letter ending. The browser's own type=email check allows "name@gmail". */
const EMAIL_RE = /^[^@\s]{1,64}@[^@\s.]+(\.[^@\s.]+)*\.[A-Za-z]{2,}$/;

export function isEmail(value: string): boolean {
  const v = value.trim();
  return v.length <= 254 && EMAIL_RE.test(v);
}

const COMMON: Record<string, string> = {
  'gmial.com': 'gmail.com', 'gmai.com': 'gmail.com', 'gmail.con': 'gmail.com', 'gmail.co': 'gmail.com', 'gmaill.com': 'gmail.com', 'gamil.com': 'gmail.com',
  'yaho.com': 'yahoo.com', 'yahoo.con': 'yahoo.com', 'hotmial.com': 'hotmail.com', 'hotmail.con': 'hotmail.com', 'outlok.com': 'outlook.com', 'outlook.con': 'outlook.com',
};

/** A likely fix for a common typo in the domain, or null. We cannot know an address is real without sending to it, so this only catches the usual slips. */
export function suggestEmail(value: string): string | null {
  const v = value.trim();
  const at = v.lastIndexOf('@');
  if (at < 1) return null;
  const fix = COMMON[v.slice(at + 1).toLowerCase()];
  return fix ? `${v.slice(0, at)}@${fix}` : null;
}
