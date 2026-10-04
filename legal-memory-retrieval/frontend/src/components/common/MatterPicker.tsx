import { useMatter, useMatters } from "@/api/resources";
import { SearchPicker, type PickerOption } from "@/components/common/SearchPicker";

export type MatterOption = { matter_id: string; matter_code: string; title: string };

/** A searchable matter field that works with any number of matters. */
export function MatterPicker({
  value,
  onChange,
  label,
  placeholder = "Find a matter by name, code or client",
  status,
  allowNone,
  noneLabel = "All matters",
  testId = "matter-picker",
  disabled,
}: {
  /** Selected matter id. */
  value: string | null;
  onChange: (matter: MatterOption | null) => void;
  label?: string;
  placeholder?: string;
  /** Only matters with this status, e.g. "Open". */
  status?: string;
  /** Offer a "no matter" choice (filters); omit it for required fields. */
  allowNone?: boolean;
  noneLabel?: string;
  testId?: string;
  disabled?: boolean;
}) {
  const selected = useMatter(value ?? "");
  const current = value && selected.data ? selected.data.matter : null;
  const found = new Map<string, MatterOption>();
  return (
    <SearchPicker
      selectedId={value}
      selectedLabel={current ? `${current.matter_code} · ${current.title}` : null}
      label={label}
      placeholder={placeholder}
      emptyLabel="Choose a matter"
      allowNone={allowNone}
      noneLabel={noneLabel}
      testId={testId}
      disabled={disabled}
      useOptions={(q) => {
        // eslint-disable-next-line react-hooks/rules-of-hooks -- called once per render by SearchPicker
        const matters = useMatters({ q: q || undefined, status, limit: 20 });
        const options: PickerOption[] = (matters.data?.items ?? []).map((m) => {
          found.set(m.matter_id, { matter_id: m.matter_id, matter_code: m.matter_code, title: m.title });
          return { id: m.matter_id, title: m.title, subtitle: [m.matter_code, m.client_name].filter(Boolean).join(" · ") };
        });
        return { options, isPending: matters.isPending };
      }}
      onSelect={(o) => onChange(o ? (found.get(o.id) ?? null) : null)}
    />
  );
}
