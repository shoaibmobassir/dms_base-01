import { useMemo, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApp } from '../context/AppContext'
import { createProject } from '../api/projects'
import type { Milestone } from '../api/projects'

const TEAMS = [
  'Corporate & M&A',
  'Dispute Resolution',
  'Arbitration',
  'Regulatory',
  'General Corporate',
]

export function CreateProjectModal({ onClose }: { onClose: () => void }) {
  const { matters, people, toast, refresh } = useApp()
  const navigate = useNavigate()
  const [title, setTitle] = useState('')
  const [matterId, setMatterId] = useState(matters[0]?.matter_id || '')
  const [team, setTeam] = useState(TEAMS[0])
  const [lead, setLead] = useState(people[0]?.name || '')
  const [deadline, setDeadline] = useState('')
  const [scope, setScope] = useState('')
  const [milestonesRaw, setMilestonesRaw] = useState('')
  const [saving, setSaving] = useState(false)

  const matterOptions = useMemo(() => matters.slice(0, 200), [matters])

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (!title.trim() || !matterId) {
      toast('Title and matter are required')
      return
    }
    setSaving(true)
    try {
      const milestones: Milestone[] = milestonesRaw
        .split(',')
        .map((m) => m.trim())
        .filter(Boolean)
        .map((m) => ({ title: m, done: false, due: deadline || undefined }))

      const created = await createProject({
        title: title.trim(),
        matter_id: matterId,
        practice_team: team,
        lead_lawyer: lead || undefined,
        deadline: deadline || undefined,
        scope: scope.trim() || undefined,
        milestones: milestones.length ? milestones : undefined,
      })
      await refresh()
      toast(`Created project “${created.title}”`)
      onClose()
      navigate(`/projects/${created.project_id}`)
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Could not create project')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal create-project-modal"
        onClick={(ev) => ev.stopPropagation()}
      >
        <div className="modal-head">
          <h2 style={{ fontSize: '1.25rem', margin: 0 }}>New project</h2>
          <button type="button" className="button button-secondary" onClick={onClose}>
            Close
          </button>
        </div>
        <form className="modal-body create-project-form" onSubmit={(ev) => void onSubmit(ev)}>
          <label>
            Title
            <input
              className="form-input"
              value={title}
              onChange={(ev) => setTitle(ev.target.value)}
              required
              placeholder="Workstream title"
            />
          </label>
          <label>
            Matter
            <select
              className="form-input"
              value={matterId}
              onChange={(ev) => setMatterId(ev.target.value)}
              required
            >
              {!matterOptions.length ? (
                <option value="">No matters available</option>
              ) : null}
              {matterOptions.map((m) => (
                <option key={m.matter_id} value={m.matter_id}>
                  {m.matter_code || m.matter_id} — {m.title}
                </option>
              ))}
            </select>
          </label>
          <label>
            Practice team
            <select
              className="form-input"
              value={team}
              onChange={(ev) => setTeam(ev.target.value)}
            >
              {TEAMS.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          <label>
            Lead lawyer
            <select
              className="form-input"
              value={lead}
              onChange={(ev) => setLead(ev.target.value)}
            >
              {people.map((p) => (
                <option key={p.member_id} value={p.name}>
                  {p.name}
                </option>
              ))}
              {!people.length ? (
                <option value={lead}>{lead || 'Counsel'}</option>
              ) : null}
            </select>
          </label>
          <label>
            Deadline
            <input
              className="form-input"
              type="date"
              value={deadline}
              onChange={(ev) => setDeadline(ev.target.value)}
            />
          </label>
          <label>
            Scope
            <textarea
              className="form-textarea"
              rows={3}
              value={scope}
              onChange={(ev) => setScope(ev.target.value)}
              placeholder="Deliverables and boundaries"
            />
          </label>
          <label>
            Milestones (comma-separated)
            <input
              className="form-input"
              value={milestonesRaw}
              onChange={(ev) => setMilestonesRaw(ev.target.value)}
              placeholder="Kickoff, Drafting, Delivery"
            />
          </label>
          <div className="form-actions">
            <button type="button" className="button button-secondary" onClick={onClose}>
              Cancel
            </button>
            <button
              type="submit"
              className="button button-primary"
              disabled={saving || !title.trim() || !matterId}
            >
              {saving ? 'Creating…' : 'Create project'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
