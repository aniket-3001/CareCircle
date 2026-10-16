import { Eye, EyeOff } from 'lucide-react';
import { useState } from 'react';
import { tr } from '../lib/i18n';

/** A password box with an eye button to show what was typed, for fixing a slip before sending. */
export function PasswordInput({ value, onChange, autoComplete, required }: { value: string; onChange: (v: string) => void; autoComplete: string; required?: boolean }): React.JSX.Element {
  const [shown, setShown] = useState(false);
  return (
    <span className="pw-wrap">
      <input type={shown ? 'text' : 'password'} value={value} autoComplete={autoComplete} required={required} onChange={(e) => onChange(e.target.value)} autoCapitalize="none" spellCheck={false} />
      <button type="button" className="pw-eye" onClick={() => setShown((s) => !s)} aria-label={shown ? tr('Hide password') : tr('Show password')} aria-pressed={shown} data-testid="pw-eye">
        {shown ? <EyeOff size={18} aria-hidden="true" /> : <Eye size={18} aria-hidden="true" />}
      </button>
    </span>
  );
}
