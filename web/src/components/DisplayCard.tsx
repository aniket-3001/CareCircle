import { Palette } from 'lucide-react';
import { Segmented } from './Segmented';
import { tr } from '../lib/i18n';
import { setTextSize, setTheme, useTextSize, useTheme, type TextSize, type Theme } from '../lib/theme';

/** How the app looks on this device: theme and text size. Kept in this browser only; nothing about it is sent to the server. */
export function DisplayCard(): React.JSX.Element {
  const theme = useTheme();
  const size = useTextSize();
  return (
    <section className="card" aria-labelledby="disp-title" data-testid="display">
      <div className="card-head"><h2 id="disp-title">{tr('Display')}</h2><Palette size={20} aria-hidden="true" /></div>
      <div className="stack">
        <div><div className="muted small">{tr('Theme')}</div>
          <Segmented<Theme> name="theme" label={tr('Theme')} value={theme} onChange={setTheme} options={[{ value: 'light', label: tr('Light') }, { value: 'dark', label: tr('Dark') }]} /></div>
        <div><div className="muted small">{tr('Text size')}</div>
          <Segmented<TextSize> name="textsize" label={tr('Text size')} value={size} onChange={setTextSize} options={[{ value: 'normal', label: tr('Normal') }, { value: 'large', label: tr('Large') }, { value: 'larger', label: tr('Larger') }]} /></div>
        <p className="muted small">{tr('Text size applies on wider screens; on a phone, use the browser zoom.')}</p>
      </div>
    </section>
  );
}
