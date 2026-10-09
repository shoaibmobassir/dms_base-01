// Keyboard shortcuts shown the way the person's keyboard labels them, and a check that a shortcut should not fire
// while the person is typing.

export const IS_MAC = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

/** "⇧⌘P" on a Mac, "Ctrl+Shift+P" elsewhere. Write shortcuts in the Mac form; ⌥ is Alt. */
export function keys(mac: string): string {
  if (IS_MAC) return mac;
  const parts: string[] = [];
  let rest = mac;
  for (const [sym, name] of [["⌃", "Ctrl"], ["⌥", "Alt"], ["⇧", "Shift"], ["⌘", "Ctrl"]] as const) {
    if (rest.includes(sym)) {
      if (!parts.includes(name)) parts.push(name);
      rest = rest.replace(sym, "");
    }
  }
  return [...parts, rest].join("+");
}

/** True when keys go to a text field or an editor, where a page shortcut must not take them. */
export function typingTarget(e: KeyboardEvent): boolean {
  const el = e.target as HTMLElement | null;
  if (!el) return false;
  if (el.isContentEditable) return true;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}
