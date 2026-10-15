/** Vayu's segmented control: native radio inputs, so keyboard and screen readers work. */
export function Segmented<T extends string | number>({ name, label, value, options, onChange }: {
  name: string;
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
}): React.JSX.Element {
  return (
    <fieldset className="segmented" style={{ border: 0, margin: 0 }}>
      <legend className="sr-only">{label}</legend>
      {options.map((o) => (
        <label key={String(o.value)} className="segmented__option">
          <input type="radio" name={name} checked={o.value === value} onChange={() => onChange(o.value)} />
          <span>{o.label}</span>
        </label>
      ))}
    </fieldset>
  );
}
