import { useEffect, useId, useRef, useState } from "react";
import { Icon } from "@/components/common/primitives";
import { cn } from "@/lib/utils";

export type PickerOption = { id: string; title: string; subtitle?: string };

/**
 * A searchable single choice for records that can be too many for a dropdown (matters, clients).
 * The caller supplies the server search through `useOptions`; nothing is chosen by default.
 */
export function SearchPicker({
  selectedId,
  selectedLabel,
  onSelect,
  useOptions,
  label,
  placeholder,
  emptyLabel = "Choose",
  allowNone,
  noneLabel = "None",
  testId,
  disabled,
}: {
  selectedId: string | null;
  /** Text shown for the current choice (its code and title). */
  selectedLabel: string | null;
  onSelect: (option: PickerOption | null) => void;
  /** Runs the search for the typed text. */
  useOptions: (query: string) => { options: PickerOption[]; isPending: boolean };
  label?: string;
  placeholder: string;
  emptyLabel?: string;
  allowNone?: boolean;
  noneLabel?: string;
  testId: string;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const boxRef = useRef<HTMLDivElement>(null);
  const labelId = useId();
  const { options, isPending } = useOptions(debounced);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 200);
    return () => clearTimeout(t);
  }, [query]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => !boxRef.current?.contains(e.target as Node) && setOpen(false);
    // Escape closes only the list, not the dialog around it: take the key before the dialog sees it.
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey, true);
    };
  }, [open]);

  const choose = (o: PickerOption | null) => {
    setOpen(false);
    setQuery("");
    onSelect(o);
  };

  return (
    <div ref={boxRef} className="relative">
      {label && (
        <span id={labelId} className="mb-1 block text-xs font-medium text-muted-foreground">
          {label}
        </span>
      )}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={disabled}
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-labelledby={label ? labelId : undefined}
        aria-label={label ? undefined : emptyLabel}
        data-testid={testId}
        className="flex w-full items-center gap-2 rounded-md border border-border bg-card px-3 py-2 text-left text-sm hover:bg-secondary/60 disabled:opacity-50"
      >
        <span className={cn("min-w-0 flex-1 truncate", !selectedId && "text-muted-foreground")}>
          {selectedId ? (selectedLabel ?? selectedId) : allowNone ? noneLabel : emptyLabel}
        </span>
        <Icon name="unfold_more" className="text-muted-foreground" style={{ fontSize: 18 }} />
      </button>
      {open && (
        <div className="absolute left-0 top-full z-50 mt-1 w-full min-w-[280px] rounded-lg border border-border bg-popover p-1.5 shadow-xl" data-testid={`${testId}-menu`}>
          <input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={placeholder}
            aria-label={placeholder}
            data-testid={`${testId}-search`}
            className="mb-1 w-full rounded-md border border-border bg-card px-2.5 py-1.5 text-[13px] focus:outline-none focus-visible:border-wine/50"
          />
          <ul role="listbox" className="max-h-64 overflow-y-auto">
            {allowNone && (
              <li>
                <button type="button" role="option" aria-selected={!selectedId} onClick={() => choose(null)} className="w-full rounded-md px-2 py-1.5 text-left text-[13px] hover:bg-secondary">
                  {noneLabel}
                </button>
              </li>
            )}
            {isPending && <li className="px-2 py-1.5 text-xs text-muted-foreground">Searching…</li>}
            {!isPending && options.length === 0 && <li className="px-2 py-1.5 text-xs text-muted-foreground">Nothing matches.</li>}
            {options.map((o) => (
              <li key={o.id}>
                <button
                  type="button"
                  role="option"
                  aria-selected={selectedId === o.id}
                  onClick={() => choose(o)}
                  data-testid={`${testId}-option`}
                  className={cn("flex w-full flex-col rounded-md px-2 py-1.5 text-left hover:bg-secondary", selectedId === o.id && "bg-wine-soft")}
                >
                  <span className="truncate text-[13px] font-medium">{o.title}</span>
                  {o.subtitle && <span className="truncate font-mono-id text-xs text-muted-foreground">{o.subtitle}</span>}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
