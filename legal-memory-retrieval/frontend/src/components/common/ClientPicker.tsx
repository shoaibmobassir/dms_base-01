import { useClient, useClients } from "@/api/resources";
import { SearchPicker, type PickerOption } from "@/components/common/SearchPicker";

/** A searchable client field. No client is chosen until the person picks one. */
export function ClientPicker({
  value,
  onChange,
  label = "Client",
  testId = "client-picker",
  activeOnly = true,
}: {
  value: string | null;
  onChange: (clientId: string | null) => void;
  label?: string;
  testId?: string;
  /** Hide clients that are on hold or waiting for a conflict check. */
  activeOnly?: boolean;
}) {
  const selected = useClient(value ?? "");
  return (
    <SearchPicker
      selectedId={value}
      selectedLabel={selected.data?.name ?? null}
      label={label}
      placeholder="Find a client by name"
      emptyLabel="Choose a client"
      testId={testId}
      useOptions={(q) => {
        // eslint-disable-next-line react-hooks/rules-of-hooks -- called once per render by SearchPicker
        const clients = useClients({ q: q || undefined });
        const options: PickerOption[] = (clients.data?.items ?? [])
          .filter((c) => !activeOnly || (c.status ?? "active") === "active")
          .map((c) => ({ id: c.client_id, title: c.name, subtitle: [c.client_id, c.industry].filter(Boolean).join(" · ") }));
        return { options, isPending: clients.isPending };
      }}
      onSelect={(o) => onChange(o?.id ?? null)}
    />
  );
}
