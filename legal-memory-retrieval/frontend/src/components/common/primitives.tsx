import type { CSSProperties, HTMLAttributes, ReactNode } from "react";
import { Link } from "react-router-dom";
import { cn } from "@/lib/utils";

export function Icon({
  name,
  className,
  style,
  ...rest
}: {
  name: string;
  className?: string;
  style?: CSSProperties;
} & Omit<HTMLAttributes<HTMLSpanElement>, "children" | "className" | "style">) {
  // Decorative unless the caller names it (then it is an image with that name).
  const labelled = Boolean((rest as { "aria-label"?: string })["aria-label"]);
  return (
    <span
      className={cn("material-symbols-outlined", className)}
      style={style}
      {...(labelled ? { role: "img" } : { "aria-hidden": true })}
      {...rest}
    >
      {name}
    </span>
  );
}

export function Eyebrow({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("eyebrow", className)}>{children}</div>;
}

export function MonoId({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn("font-mono-id text-[0.8em] text-muted-foreground", className)}>{children}</span>;
}

export function PageHeader({
  eyebrow,
  title,
  subtitle,
  actions,
  children,
  className,
  count,
  compact,
}: {
  eyebrow?: ReactNode;
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
  className?: string;
  /** Shown after the title, e.g. "168 matters". */
  count?: ReactNode;
  /** Work pages (lists, tools): a plain title instead of the display headline. */
  compact?: boolean;
}) {
  return (
    <header className={cn("animate-rise", className)}>
      {eyebrow && <Eyebrow className={compact ? "mb-2" : "mb-3"}>{eyebrow}</Eyebrow>}
      <div className={cn("flex flex-col md:flex-row md:items-end md:justify-between", compact ? "gap-3" : "gap-5")}>
        <div className="max-w-2xl">
          <h1 className={cn("font-display leading-[1.05] text-ink", compact ? "text-3xl" : "text-4xl sm:text-5xl")}>
            {title}
            {count != null && (
              <span className="ml-3 align-middle font-sans text-base font-normal text-muted-foreground" data-testid="page-count">
                {count}
              </span>
            )}
          </h1>
          {subtitle && <p className={cn("text-muted-foreground", compact ? "mt-1.5 text-sm" : "mt-3 text-base")}>{subtitle}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {children}
    </header>
  );
}

const STATUS_STYLES: Record<string, string> = {
  Active: "text-wine",
  Pending: "text-warning",
  "Needs review": "text-warning",
  Closed: "text-muted-foreground",
  Archived: "text-muted-foreground",
  Restricted: "text-destructive",
  Processing: "text-warning",
  Indexed: "text-success",
  Connected: "text-success",
  Open: "text-wine",
  Investigating: "text-warning",
  Resolved: "text-success",
  Dismissed: "text-muted-foreground",
  Allowed: "text-success",
  Live: "text-wine",
};

const STATUS_NORM: Record<string, string> = {
  open: "text-wine",
  active: "text-wine",
  live: "text-wine",
  closed: "text-muted-foreground",
  archived: "text-muted-foreground",
  indexed: "text-success",
  connected: "text-success",
  pending: "text-warning",
  processing: "text-warning",
  restricted: "text-destructive",
};

export function StatusLabel({ status, className }: { status: string; className?: string }) {
  const tone = STATUS_STYLES[status] || STATUS_NORM[status.toLowerCase()] || "text-muted-foreground";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.12em]",
        tone,
        className,
      )}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current opacity-70" />
      {status}
    </span>
  );
}

export function SectionLabel({
  children,
  className,
  right,
}: {
  children: ReactNode;
  className?: string;
  right?: ReactNode;
}) {
  return (
    <div className={cn("mb-3 flex items-center justify-between", className)}>
      <div className="meta-label">{children}</div>
      {right}
    </div>
  );
}

export function Hairline({ className }: { className?: string }) {
  return <div className={cn("border-t border-border", className)} />;
}

export function EmptyState({
  icon = "search_off",
  title,
  description,
  tips,
  action,
}: {
  icon?: string;
  title: ReactNode;
  description?: ReactNode;
  tips?: string[];
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-start rounded-lg border border-dashed border-border bg-card px-8 py-12 animate-fade">
      <Icon name={icon} className="text-muted-foreground" style={{ fontSize: 28 }} />
      <h3 className="mt-3 font-display text-xl text-ink">{title}</h3>
      {description && <p className="mt-3 max-w-md text-sm text-muted-foreground">{description}</p>}
      {tips && (
        <ul className="mt-4 space-y-1.5 text-sm text-muted-foreground">
          {tips.map((t) => (
            <li key={t} className="flex items-start gap-2">
              <span className="mt-2 h-1 w-1 rounded-full bg-wine" />
              {t}
            </li>
          ))}
        </ul>
      )}
      {action && <div className="mt-6">{action}</div>}
    </div>
  );
}

export function ErrorState({
  title = "We couldn't complete the search",
  description = "The knowledge index did not respond. Your documents have not been modified.",
  onRetry,
}: {
  title?: string;
  description?: string;
  onRetry?: () => void;
}) {
  return (
    <div className="rounded-lg border border-border bg-card px-8 py-12 animate-fade">
      <h3 className="text-base font-semibold text-destructive" role="alert">{title}</h3>
      <p className="mt-2 max-w-md text-sm text-muted-foreground">{description}</p>
      <div className="mt-6 flex gap-2">
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            data-testid="error-retry"
            className="rounded-md bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground transition-colors hover:opacity-90"
          >
            Try again
          </button>
        )}
      </div>
    </div>
  );
}

export function RestrictedState() {
  return (
    <div className="rounded-lg border border-border bg-card px-8 py-12">
      <div className="flex items-center gap-2 text-destructive">
        <Icon name="lock" />
        <h3 className="eyebrow text-destructive">Restricted knowledge</h3>
      </div>
      <p className="mt-3 max-w-md text-sm text-muted-foreground">
        This information exists within the firm&apos;s knowledge system, but your current permissions do not allow access.
        Contact your matter administrator if you believe you should have access.
      </p>
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded bg-muted", className)} />;
}

export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-px">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-6 border-b border-border py-4">
          <Skeleton className="h-4 w-1/3" />
          <Skeleton className="h-4 w-1/5" />
          <Skeleton className="h-4 w-1/6" />
          <Skeleton className="ml-auto h-4 w-16" />
        </div>
      ))}
    </div>
  );
}

/** Placeholder shaped like a record page: title, a line of facts, then two blocks of text. */
export function DetailSkeleton() {
  return (
    <div className="space-y-8" role="status" aria-label="Loading">
      <div className="space-y-3">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="h-9 w-2/3" />
        <Skeleton className="h-4 w-1/3" />
      </div>
      <div className="space-y-3">
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-11/12" />
        <Skeleton className="h-4 w-4/5" />
      </div>
      <TableSkeleton rows={3} />
    </div>
  );
}

export function Chip({
  children,
  className,
  tone = "muted",
}: {
  children: ReactNode;
  className?: string;
  tone?: "muted" | "wine" | "accent";
}) {
  const tones = {
    muted: "bg-secondary text-secondary-foreground",
    wine: "bg-wine-soft text-wine",
    accent: "bg-accent text-accent-foreground",
  };
  return (
    <span className={cn("inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium", tones[tone], className)}>
      {children}
    </span>
  );
}

export function SearchField({
  value,
  onChange,
  placeholder,
  testId,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  testId?: string;
}) {
  return (
    <div className="flex items-center gap-2 rounded-md border border-border bg-card px-3 py-2">
      <Icon name="search" className="text-muted-foreground" style={{ fontSize: 18 }} />
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        data-testid={testId}
        className="w-full bg-transparent text-sm focus:outline-none"
      />
    </div>
  );
}

export function Action({
  children,
  onClick,
  to,
  primary,
  icon,
  className,
  testId,
}: {
  children: ReactNode;
  onClick?: () => void;
  to?: string;
  primary?: boolean;
  icon?: string;
  className?: string;
  testId?: string;
}) {
  const cls = cn(
    "inline-flex items-center gap-2 rounded-md px-3.5 py-2 text-sm font-semibold transition-all duration-150 active:scale-[0.98]",
    primary ? "bg-primary text-primary-foreground hover:opacity-90" : "border border-border bg-card text-foreground hover:bg-secondary",
    className,
  );
  const inner = (
    <>
      {icon && <Icon name={icon} style={{ fontSize: 18 }} />}
      {children}
    </>
  );
  if (to) {
    return (
      <Link to={to} data-testid={testId} className={cls}>
        {inner}
      </Link>
    );
  }
  return (
    <button type="button" onClick={onClick} data-testid={testId} className={cls}>
      {inner}
    </button>
  );
}
