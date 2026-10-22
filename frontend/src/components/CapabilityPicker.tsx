import { capabilities, type Capability } from "../api/platform";
export function CapabilityPicker({ selected, onChange, disabled = false }: {
  selected: Capability[]; onChange: (next: Capability[]) => void; disabled?: boolean;
}) {
  return <fieldset className="capabilityPicker" disabled={disabled}><legend>平台基础能力</legend>
    {capabilities.map((item) => <label key={item.id}><input type="checkbox" checked={selected.includes(item.id)}
      onChange={(event) => onChange(event.target.checked ? [...selected, item.id] : selected.filter((id) => id !== item.id))} />
      <span><strong>{item.name}</strong><small>{item.description}</small></span></label>)}
  </fieldset>;
}
