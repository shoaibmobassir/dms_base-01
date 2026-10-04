import { useId, type ReactNode } from "react";
import { cn } from "@/lib/utils";

/** Class for a text input, select or textarea inside a form. */
export const fieldControl =
  "w-full rounded-md border border-border bg-card px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:border-wine/60 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-wine/30 disabled:opacity-50";

/**
 * A form field with a visible label, an optional hint and an error. Pass the control as a
 * function to receive the id that ties the label (and hint) to it.
 */
export function Field({
  label,
  hint,
  error,
  className,
  children,
}: {
  label: string;
  hint?: string;
  error?: string | null;
  className?: string;
  children: (props: { id: string; "aria-describedby"?: string; "aria-invalid"?: boolean }) => ReactNode;
}) {
  const id = useId();
  const noteId = `${id}-note`;
  const note = error || hint;
  return (
    <div className={cn("block", className)}>
      <label htmlFor={id} className="mb-1 block text-xs font-medium text-muted-foreground">
        {label}
      </label>
      {children({ id, "aria-describedby": note ? noteId : undefined, "aria-invalid": error ? true : undefined })}
      {note && (
        <p id={noteId} className={cn("mt-1 text-xs", error ? "text-destructive" : "text-muted-foreground")} role={error ? "alert" : undefined}>
          {note}
        </p>
      )}
    </div>
  );
}
