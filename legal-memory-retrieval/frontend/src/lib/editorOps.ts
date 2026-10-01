import type { EditOp, EditParagraph, EditRun } from '@/api/editor'

/** A paragraph as it stands in the editor: the original paragraph id it came from (or null
 * if new), its text, style and formatted runs. */
export type LivePara = { pid: number | null; text: string; style: string; runs: EditRun[] }

type Flags = string // "biu" letters present, e.g. "b", "bi", ""

function charFlags(runs: EditRun[]): Flags[] {
  const out: Flags[] = []
  for (const r of runs) {
    const f = `${r.bold ? 'b' : ''}${r.italic ? 'i' : ''}${r.underline ? 'u' : ''}`
    for (let i = 0; i < r.text.length; i++) out.push(f)
  }
  return out
}

/** Same text, same bold/italic/underline on every character (run boundaries do not matter). */
export function sameFormatting(a: EditRun[], b: EditRun[]): boolean {
  const fa = charFlags(a)
  const fb = charFlags(b)
  return fa.length === fb.length && fa.every((f, i) => f === fb[i])
}

/** Adjacent runs with the same formatting merged, empty runs dropped. */
export function mergeRuns(runs: EditRun[]): EditRun[] {
  const out: EditRun[] = []
  for (const r of runs) {
    if (!r.text) continue
    const last = out[out.length - 1]
    if (last && last.bold === r.bold && last.italic === r.italic && last.underline === r.underline) last.text += r.text
    else out.push({ ...r })
  }
  return out
}

/**
 * Edit ops that turn the base paragraphs into what the editor holds now.
 *
 * Paragraph ids travel with the text in the editor, so a paragraph keeps its identity
 * while it is edited. Rules:
 *  - a known id whose text changed → replace (with its formatted runs, and its style when
 *    that changed); same text but other formatting or style → format; ids never seen → delete
 *  - a paragraph with no id (typed, pasted, split off) → insert after the last original
 *    paragraph above it, with its style and runs
 *  - an id seen twice (a copy) or out of order (moved) → its later occurrence is an insert,
 *    so nothing is reordered silently
 * ``styles`` are the styles the document defines; others are never sent.
 * Returns ops plus paragraphs that could not be placed (new text above the first paragraph).
 */
export function computeOps(
  basis: EditParagraph[],
  liveIn: LivePara[],
  styles: string[] = [],
): { ops: EditOp[]; unplaced: string[] } {
  const base = new Map(basis.map((p) => [p.pid, p]))
  // Enter at the start of a paragraph leaves the id on the new empty line above and the
  // original text on an id-less line below: give the id back to the text.
  const live = liveIn.map((p) => ({ ...p }))
  for (let i = 0; i + 1 < live.length; i++) {
    const cur = live[i]
    const next = live[i + 1]
    if (cur.pid !== null && !cur.text.trim() && next.pid === null && next.text === base.get(cur.pid)?.text) {
      next.pid = cur.pid
      next.style = cur.style
      cur.pid = null
      cur.style = 'Normal'
    }
  }
  const known = new Set(styles)
  const styleOf = (s: string) => (known.has(s) ? s : undefined)
  const seen = new Set<number>()
  const ops: EditOp[] = []
  const unplaced: string[] = []
  let anchor: number | null = null
  for (const para of live) {
    const pid = para.pid
    const orig = pid !== null ? base.get(pid) : undefined
    const isKnown = pid !== null && orig !== undefined && !seen.has(pid) && (anchor === null || pid > anchor)
    const runs = mergeRuns(para.runs)
    if (isKnown && pid !== null && orig) {
      seen.add(pid)
      const restyled = para.style !== orig.style ? styleOf(para.style) : undefined
      if (para.text !== orig.text) {
        ops.push({ op: 'replace', pid, text: para.text, runs, ...(restyled ? { style: restyled } : {}) })
      } else {
        const reformatted = !sameFormatting(runs, orig.runs)
        if (restyled || reformatted) {
          ops.push({ op: 'format', pid, ...(restyled ? { style: restyled } : {}), ...(reformatted ? { runs } : {}) })
        }
      }
      anchor = pid
    } else if (anchor === null) {
      if (para.text.trim()) unplaced.push(para.text)
    } else if (para.text.trim()) {
      const style = styleOf(para.style)
      ops.push({ op: 'insert_after', pid: anchor, text: para.text, runs, ...(style ? { style } : {}) })
    }
  }
  for (const p of basis) if (!seen.has(p.pid)) ops.push({ op: 'delete', pid: p.pid })
  return { ops, unplaced }
}

const plain = (text: string): EditRun[] => [{ text, bold: false, italic: false, underline: false }]

/** The editor's paragraphs after applying saved ops to the base (restoring a draft). */
export function applyOps(basis: EditParagraph[], ops: EditOp[]): (EditParagraph & { pidLive: number | null })[] {
  const changed = new Map<number, Extract<EditOp, { op: 'replace' | 'format' }>>()
  const deleted = new Set<number>()
  const inserts = new Map<number, Extract<EditOp, { op: 'insert_after' }>[]>()
  for (const op of ops) {
    if (op.op === 'replace' || op.op === 'format') changed.set(op.pid, op)
    else if (op.op === 'delete') deleted.add(op.pid)
    else inserts.set(op.pid, [...(inserts.get(op.pid) ?? []), op])
  }
  const out: (EditParagraph & { pidLive: number | null })[] = []
  for (const p of basis) {
    if (!deleted.has(p.pid)) {
      const op = changed.get(p.pid)
      const text = op?.op === 'replace' ? op.text : p.text
      const runs = op?.runs ?? (op?.op === 'replace' ? plain(op.text) : p.runs)
      out.push({ ...p, pidLive: p.pid, text, runs, style: op?.style ?? p.style })
    }
    for (const ins of inserts.get(p.pid) ?? []) {
      out.push({ pid: -1, pidLive: null, style: ins.style ?? 'Normal', text: ins.text, runs: ins.runs ?? plain(ins.text) })
    }
  }
  return out
}

/** Word-level diff for the changes panel. */
export function wordDiff(a: string, b: string): { t: 'eq' | 'ins' | 'del'; text: string }[] {
  const ta = a.match(/\s+|[^\s]+/g) ?? []
  const tb = b.match(/\s+|[^\s]+/g) ?? []
  const n = ta.length
  const m = tb.length
  // LCS table (paragraph-sized inputs only).
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0))
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i][j] = ta[i] === tb[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
  const out: { t: 'eq' | 'ins' | 'del'; text: string }[] = []
  const push = (t: 'eq' | 'ins' | 'del', text: string) => {
    const last = out[out.length - 1]
    if (last && last.t === t) last.text += text
    else out.push({ t, text })
  }
  let i = 0
  let j = 0
  while (i < n && j < m) {
    if (ta[i] === tb[j]) {
      push('eq', ta[i])
      i++
      j++
    } else if (dp[i + 1][j] >= dp[i][j + 1]) push('del', ta[i++])
    else push('ins', tb[j++])
  }
  while (i < n) push('del', ta[i++])
  while (j < m) push('ins', tb[j++])
  return out
}
