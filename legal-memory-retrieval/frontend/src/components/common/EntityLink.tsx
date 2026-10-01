import { Link } from "react-router-dom";
import { cn } from "@/lib/utils";
import { useInspector } from "@/components/common/Inspector";
import { initials } from "@/context/AppContext";

/** Matter code linking to the matter page, plus a name that opens the inspector. */
export function MatterLink({ id, code, name, className }: { id: string; code?: string; name?: string; className?: string }) {
  const inspector = useInspector();
  return (
    <span className={cn("inline-flex items-baseline gap-2", className)}>
      <Link to={`/matters/${id}`} className="font-mono-id text-[0.82em] text-wine hover:underline" data-testid={`matterlink-${id}`}>
        {code || id}
      </Link>
      {name && (
        <button type="button" onClick={() => inspector?.open({ type: "matter", id })} className="text-left text-foreground hover:text-wine">
          {name}
        </button>
      )}
    </span>
  );
}

export function PersonLink({ id, name, className }: { id: string; name: string; className?: string }) {
  const inspector = useInspector();
  return (
    <button
      type="button"
      onClick={() => inspector?.open({ type: "person", id })}
      className={cn("inline-flex items-center gap-2 hover:text-wine", className)}
      data-testid={`personlink-${id}`}
    >
      <PersonAvatar person={{ name, initials: initials(name) }} />
      <span>{name}</span>
    </button>
  );
}

export function ClientLink({ id, name, className }: { id: string; name: string; className?: string }) {
  const inspector = useInspector();
  return (
    <button
      type="button"
      onClick={() => inspector?.open({ type: "client", id })}
      className={cn("text-left hover:text-wine", className)}
      data-testid={`clientlink-${id}`}
    >
      {name}
    </button>
  );
}

export function PersonAvatar({ person, size = 22 }: { person: { initials: string; name?: string }; size?: number }) {
  return (
    <span
      className="inline-flex shrink-0 items-center justify-center rounded-full bg-wine-soft font-semibold text-wine"
      style={{ width: size, height: size, fontSize: size * 0.4 }}
      aria-hidden
    >
      {person.initials}
    </span>
  );
}
