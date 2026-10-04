import { usePeople } from "@/api/resources";
import { SearchPicker, type PickerOption } from "@/components/common/SearchPicker";

/** A searchable person field. Nobody is chosen until the person picks one. */
export function PersonPicker({
  value,
  onChange,
  exclude,
  label = "Person",
  testId = "person-picker",
}: {
  value: string | null;
  onChange: (memberId: string | null) => void;
  /** People already chosen elsewhere (for example already on the team). */
  exclude?: ReadonlySet<string>;
  label?: string;
  testId?: string;
}) {
  const people = usePeople();
  const all = people.data ?? [];
  const selected = all.find((p) => p.member_id === value);
  return (
    <SearchPicker
      selectedId={value}
      selectedLabel={selected ? `${selected.name}, ${selected.role}` : null}
      label={label}
      placeholder="Find someone by name, role, office or practice"
      emptyLabel="Choose a person"
      testId={testId}
      useOptions={(q) => {
        const needle = q.toLowerCase();
        const options: PickerOption[] = all
          .filter((p) => !exclude?.has(p.member_id))
          .filter((p) => !needle || [p.name, p.role, p.office ?? "", ...p.practice_areas].some((v) => v.toLowerCase().includes(needle)))
          .slice(0, 30)
          .map((p) => ({ id: p.member_id, title: p.name, subtitle: [p.role, p.office].filter(Boolean).join(" · ") }));
        return { options, isPending: people.isPending };
      }}
      onSelect={(o) => onChange(o?.id ?? null)}
    />
  );
}
