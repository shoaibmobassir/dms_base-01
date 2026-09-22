import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  assignDocument,
  createFolder,
  deleteFolder,
  exportProject,
  getProject,
  getProjectActivity,
  getProjectDirectory,
  getProjectDocuments,
  moveDocumentFolder,
  toggleMilestone,
  type ProjectDetail,
  type ProjectFolder,
} from '../api/projects'
import {
  compareVersions,
  createDevelopingVersion,
  getVersion,
  listVersions,
  type DocVersion,
} from '../api/documents'
import { useApp } from '../context/AppContext'

type Tab = 'overview' | 'documents' | 'activity'

export function ProjectDetailPage() {
  const { projectId = '' } = useParams()
  const { toast, people } = useApp()
  const navigate = useNavigate()
  const [project, setProject] = useState<ProjectDetail | null>(null)
  const [docs, setDocs] = useState<Array<Record<string, unknown>>>([])
  const [folderTree, setFolderTree] = useState<ProjectFolder[]>([])
  const [activity, setActivity] = useState<Array<Record<string, unknown>>>([])
  const [tab, setTab] = useState<Tab>('overview')
  const [folderFilter, setFolderFilter] = useState('__all__')
  const [docSearch, setDocSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [versionPanel, setVersionPanel] = useState<{
    docId: string
    versions: DocVersion[]
    content?: string
    title?: string
  } | null>(null)

  const reload = useCallback(async () => {
    if (!projectId) return
    setLoading(true)
    try {
      const [detail, directory, documents, act] = await Promise.all([
        getProject(projectId),
        getProjectDirectory(projectId).catch(() => ({
          tree: [] as ProjectFolder[],
          folders: [] as ProjectFolder[],
          folder_tree: [] as ProjectFolder[],
        })),
        getProjectDocuments(projectId).catch(() => ({ items: [], documents: [] })),
        getProjectActivity(projectId).catch(() => ({ items: [] })),
      ])
      setProject(detail)
      setFolderTree(
        directory.folder_tree || directory.tree || directory.folders || [],
      )
      const docList =
        documents.items ||
        documents.documents ||
        (detail.documents as Array<Record<string, unknown>>) ||
        []
      setDocs(docList)
      setActivity(act.items || detail.recent_activity || [])
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Failed to load project')
      setProject(null)
    } finally {
      setLoading(false)
    }
  }, [projectId, toast])

  useEffect(() => {
    void reload()
  }, [reload])

  const filteredDocs = useMemo(() => {
    let list = docs
    if (folderFilter === '__root__') {
      list = list.filter((d) => !d.folder_id)
    } else if (folderFilter !== '__all__') {
      list = list.filter((d) => d.folder_id === folderFilter)
    }
    const q = docSearch.trim().toLowerCase()
    if (q) {
      list = list.filter(
        (d) =>
          String(d.title || '')
            .toLowerCase()
            .includes(q) ||
          String(d.document_id || '')
            .toLowerCase()
            .includes(q),
      )
    }
    return list
  }, [docs, folderFilter, docSearch])

  async function onExport() {
    try {
      const data = await exportProject(projectId)
      if (!data.export) {
        toast('Export failed')
        return
      }
      const blob = new Blob([JSON.stringify(data.export, null, 2)], {
        type: 'application/json',
      })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${projectId}-manifest.json`
      a.click()
      URL.revokeObjectURL(url)
      toast('Project manifest downloaded')
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Export failed')
    }
  }

  async function onAddFolder() {
    const parent =
      folderFilter.startsWith('__') ? null : folderFilter
    const name = window.prompt(parent ? 'New subfolder name:' : 'New folder name:')
    if (!name?.trim()) return
    try {
      await createFolder(projectId, name.trim(), parent)
      toast(`Created folder “${name.trim()}”`)
      await reload()
      setTab('documents')
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Could not create folder')
    }
  }

  async function onDeleteFolder(folder: ProjectFolder) {
    if (!window.confirm(`Delete folder “${folder.name}”?`)) return
    try {
      await deleteFolder(projectId, folder.folder_id)
      if (folderFilter === folder.folder_id) setFolderFilter('__all__')
      toast(`Deleted folder “${folder.name}”`)
      await reload()
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Could not delete folder')
    }
  }

  async function onAssignDoc() {
    const docId = window.prompt('Enter document ID to assign (e.g. DOC-00001):')
    if (!docId?.trim()) return
    try {
      await assignDocument(projectId, docId.trim().toUpperCase())
      toast('Document assigned')
      await reload()
      setTab('documents')
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Could not assign document')
    }
  }

  async function onMoveDoc(documentId: string, folderId: string) {
    try {
      await moveDocumentFolder(projectId, documentId, folderId || null)
      toast('Document moved')
      await reload()
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Move failed')
    }
  }

  async function onToggleMilestone(index: number, done: boolean) {
    try {
      await toggleMilestone(projectId, index, done)
      toast('Milestone updated')
      await reload()
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Could not update milestone')
    }
  }

  async function onDevelop(docId: string) {
    const author = people[0]?.name || 'Counsel'
    try {
      const res = await createDevelopingVersion(docId, author)
      toast(`Created ${res.version?.version_label || 'developing version'}`)
      await reload()
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Could not create version')
    }
  }

  async function openVersions(docId: string) {
    try {
      const data = await listVersions(docId)
      const versions = data.versions || []
      if (!versions.length) {
        toast('No version history yet')
        navigate(`/documents/${docId}`)
        return
      }
      setVersionPanel({ docId, versions, title: 'Version history' })
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Could not load versions')
    }
  }

  async function viewVersion(docId: string, versionId: string) {
    try {
      const data = await getVersion(docId, versionId)
      const v = data.version
      setVersionPanel({
        docId,
        versions: versionPanel?.versions || [],
        content: v?.body || '',
        title: v?.title || v?.version_label || 'Version',
      })
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Could not load version')
    }
  }

  async function compareLatest(docId: string, versions: DocVersion[]) {
    if (versions.length < 2) return
    try {
      const diff = await compareVersions(
        docId,
        versions[0].version_id,
        versions[1].version_id,
      )
      setVersionPanel({
        docId,
        versions,
        title: `Diff v${diff.version_a?.version_number} → v${diff.version_b?.version_number}`,
        content: diff.diff || 'No diff returned',
      })
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Diff failed')
    }
  }

  if (loading) return <div className="empty">Loading project…</div>
  if (!project) return <div className="empty">Project not found or not visible under ACL.</div>

  const milestones = project.milestones || []
  const team = Array.isArray(project.team) ? project.team : []
  const teamLabel =
    typeof project.team === 'string'
      ? project.team
      : project.practice_team || 'Workstream'
  const doneCount = milestones.filter((m) => m.done).length

  return (
    <div>
      <div className="label-sm" style={{ marginBottom: 12, color: 'var(--muted-foreground)' }}>
        <Link to="/projects" style={{ color: 'var(--muted-foreground)' }}>
          Projects
        </Link>
        <span style={{ margin: '0 8px' }}>/</span>
        {project.matter_id ? (
          <>
            <Link
              to={`/matters/${project.matter_id}`}
              style={{ color: 'var(--muted-foreground)' }}
            >
              {project.matter_code || project.matter_id}
            </Link>
            <span style={{ margin: '0 8px' }}>/</span>
          </>
        ) : null}
        <span style={{ color: 'var(--primary)', fontWeight: 600 }}>
          {project.project_id}
        </span>
      </div>

      <div className="entity-header surface">
        <div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
            <span className="chip">{teamLabel}</span>
            <span className="status">{project.status || 'In Progress'}</span>
          </div>
          <h1 className="page-title">{project.title}</h1>
          <p className="page-sub">
            {project.client_name || 'Client'}
            {project.lead_lawyer ? ` · Lead: ${project.lead_lawyer}` : ''}
            {project.deadline ? ` · Due ${project.deadline}` : ''}
            {` · ${project.progress ?? 0}%`}
          </p>
          <div className="progress-track" style={{ marginTop: 12, maxWidth: 320 }}>
            <div
              className="progress-fill"
              style={{ width: `${Math.min(100, project.progress || 0)}%` }}
            />
          </div>
        </div>
        <div className="entity-actions">
          <button type="button" className="button button-secondary" onClick={() => void onExport()}>
            Export
          </button>
          <button
            type="button"
            className="button button-secondary"
            onClick={() =>
              navigate(
                `/ask?q=${encodeURIComponent(`What are the key findings in project ${project.project_id}?`)}`,
              )
            }
          >
            Ask project
          </button>
          <button type="button" className="button button-primary" onClick={() => void onAddFolder()}>
            New folder
          </button>
        </div>
      </div>

      <div className="tabs-nav">
        {(
          [
            ['overview', 'Overview'],
            ['documents', `Documents (${docs.length})`],
            ['activity', `Activity (${activity.length})`],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            className={`tab-btn${tab === id ? ' is-active' : ''}`}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'overview' ? (
        <div className="split-2">
          <div className="stack-gap">
            <section className="surface pad-card">
              <div className="section-label">Scope</div>
              <p style={{ margin: 0, lineHeight: 1.6 }}>
                {project.scope || 'No scope defined yet.'}
              </p>
            </section>
            <section className="surface pad-card">
              <div className="section-label">
                Milestones · {doneCount}/{milestones.length}
              </div>
              <div className="stack-gap-sm">
                {milestones.map((m, idx) => (
                  <label key={idx} className="milestone-row">
                    <input
                      type="checkbox"
                      checked={Boolean(m.done)}
                      onChange={(e) => void onToggleMilestone(idx, e.target.checked)}
                    />
                    <span className={m.done ? 'is-done' : ''}>{m.title}</span>
                    <span className="mono metadata-xs">{m.due || project.deadline || ''}</span>
                  </label>
                ))}
                {!milestones.length ? (
                  <div className="empty" style={{ border: 'none' }}>
                    No milestones defined.
                  </div>
                ) : null}
              </div>
            </section>
          </div>
          <div className="stack-gap">
            <section className="surface pad-card">
              <div className="section-label">Team</div>
              {team.slice(0, 8).map((t, i) => (
                <div key={i} className="list-row">
                  <div>
                    <div style={{ fontWeight: 600 }}>{String(t.name || 'Member')}</div>
                    <div className="metadata-xs">
                      {String(t.role_on_matter || t.role || 'Team member')}
                    </div>
                  </div>
                </div>
              ))}
              {!team.length ? <div className="empty" style={{ border: 'none' }}>No team listed.</div> : null}
            </section>
            <section className="surface pad-card">
              <div className="section-label">Recent documents</div>
              {docs.slice(0, 6).map((d) => (
                <Link
                  key={String(d.document_id)}
                  className="list-row"
                  to={`/documents/${String(d.document_id)}`}
                >
                  <div>
                    <div style={{ fontWeight: 600 }}>{String(d.title || d.document_id)}</div>
                    <div className="metadata-xs">{String(d.document_type || 'Document')}</div>
                  </div>
                </Link>
              ))}
              {!docs.length ? (
                <div className="empty" style={{ border: 'none' }}>No documents yet.</div>
              ) : null}
            </section>
          </div>
        </div>
      ) : null}

      {tab === 'documents' ? (
        <div className="project-workspace">
          <aside className="folder-panel surface">
            <div className="folder-panel-head">
              <span>Directory</span>
              <button type="button" className="button button-secondary" onClick={() => void onAddFolder()}>
                +
              </button>
            </div>
            <button
              type="button"
              className={`folder-item${folderFilter === '__all__' ? ' is-active' : ''}`}
              onClick={() => setFolderFilter('__all__')}
            >
              All documents <em>{docs.length}</em>
            </button>
            <button
              type="button"
              className={`folder-item${folderFilter === '__root__' ? ' is-active' : ''}`}
              onClick={() => setFolderFilter('__root__')}
            >
              Project root <em>{docs.filter((d) => !d.folder_id).length}</em>
            </button>
            <FolderTree
              nodes={folderTree}
              selected={folderFilter}
              onSelect={setFolderFilter}
              onDelete={(f) => void onDeleteFolder(f)}
            />
          </aside>
          <section className="surface pad-card" style={{ minWidth: 0 }}>
            <div className="directory-tools" style={{ marginBottom: 12 }}>
              <div className="inline-search">
                <span className="material-symbols-outlined" style={{ fontSize: 17 }}>
                  search
                </span>
                <input
                  value={docSearch}
                  onChange={(e) => setDocSearch(e.target.value)}
                  placeholder="Search project documents"
                />
              </div>
              <button type="button" className="button button-secondary" onClick={() => void onAssignDoc()}>
                Assign document
              </button>
            </div>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Document</th>
                    <th>Folder</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredDocs.map((d) => {
                    const id = String(d.document_id)
                    return (
                      <tr key={id}>
                        <td>
                          <Link to={`/documents/${id}`} style={{ fontWeight: 600 }}>
                            {String(d.title || id)}
                          </Link>
                          <div className="metadata-xs">{id}</div>
                        </td>
                        <td>
                          <select
                            className="form-input"
                            value={String(d.folder_id || '')}
                            onChange={(e) => void onMoveDoc(id, e.target.value)}
                          >
                            <option value="">Root</option>
                            {flattenFolders(folderTree).map((f) => (
                              <option key={f.folder_id} value={f.folder_id}>
                                {f.name}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td>
                          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                            <button
                              type="button"
                              className="button button-secondary"
                              onClick={() => void onDevelop(id)}
                            >
                              Develop
                            </button>
                            <button
                              type="button"
                              className="button button-secondary"
                              onClick={() => void openVersions(id)}
                            >
                              Versions
                            </button>
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              {!filteredDocs.length ? <div className="empty">No documents in this folder.</div> : null}
            </div>
          </section>
        </div>
      ) : null}

      {tab === 'activity' ? (
        <section className="surface pad-card stack-gap-sm">
          {activity.map((ev, i) => (
            <div key={i} className="list-row">
              <div>
                <div style={{ fontWeight: 600 }}>
                  {String(ev.action || ev.event_type || ev.title || 'Event')}
                </div>
                <div className="metadata-xs">
                  {String(ev.target_title || ev.description || '')}
                  {ev.created_at ? ` · ${String(ev.created_at)}` : ''}
                </div>
              </div>
            </div>
          ))}
          {!activity.length ? <div className="empty">No activity yet.</div> : null}
        </section>
      ) : null}

      {versionPanel ? (
        <div className="drawer-overlay" onClick={() => setVersionPanel(null)}>
          <aside className="drawer" onClick={(e) => e.stopPropagation()}>
            <div className="drawer-head">
              <h3>{versionPanel.title || 'Versions'}</h3>
              <button type="button" className="button button-secondary" onClick={() => setVersionPanel(null)}>
                Close
              </button>
            </div>
            <div className="drawer-body">
              {versionPanel.content != null ? (
                <>
                  <button
                    type="button"
                    className="button button-secondary"
                    style={{ marginBottom: 12 }}
                    onClick={() => void openVersions(versionPanel.docId)}
                  >
                    ← All versions
                  </button>
                  <pre className="diff-pane">{versionPanel.content}</pre>
                </>
              ) : (
                <>
                  {versionPanel.versions.map((v) => (
                    <button
                      key={v.version_id}
                      type="button"
                      className="list-row"
                      style={{ width: '100%', textAlign: 'left' }}
                      onClick={() => void viewVersion(versionPanel.docId, v.version_id)}
                    >
                      <div>
                        <div style={{ fontWeight: 600 }}>
                          v{v.version_number} · {v.version_label || v.title || 'Version'}
                        </div>
                        <div className="metadata-xs">
                          {v.author_name || 'Unknown'} · {v.version_status || ''} ·{' '}
                          {v.created_at || ''}
                        </div>
                      </div>
                    </button>
                  ))}
                  {versionPanel.versions.length >= 2 ? (
                    <button
                      type="button"
                      className="button button-secondary"
                      style={{ marginTop: 12 }}
                      onClick={() =>
                        void compareLatest(versionPanel.docId, versionPanel.versions)
                      }
                    >
                      Compare latest two
                    </button>
                  ) : null}
                </>
              )}
            </div>
          </aside>
        </div>
      ) : null}
    </div>
  )
}

function flattenFolders(nodes: ProjectFolder[], acc: ProjectFolder[] = []): ProjectFolder[] {
  for (const n of nodes) {
    acc.push(n)
    if (n.children?.length) flattenFolders(n.children, acc)
  }
  return acc
}

function FolderTree({
  nodes,
  selected,
  onSelect,
  onDelete,
  depth = 0,
}: {
  nodes: ProjectFolder[]
  selected: string
  onSelect: (id: string) => void
  onDelete: (f: ProjectFolder) => void
  depth?: number
}) {
  return (
    <>
      {nodes.map((folder) => (
        <div key={folder.folder_id} style={{ paddingLeft: depth * 12 }}>
          <div className={`folder-item${selected === folder.folder_id ? ' is-active' : ''}`}>
            <button type="button" onClick={() => onSelect(folder.folder_id)}>
              {folder.name} <em>{folder.document_count ?? 0}</em>
            </button>
            <button
              type="button"
              className="folder-delete"
              aria-label={`Delete ${folder.name}`}
              onClick={() => onDelete(folder)}
            >
              ×
            </button>
          </div>
          {folder.children?.length ? (
            <FolderTree
              nodes={folder.children}
              selected={selected}
              onSelect={onSelect}
              onDelete={onDelete}
              depth={depth + 1}
            />
          ) : null}
        </div>
      ))}
    </>
  )
}
