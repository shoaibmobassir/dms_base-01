import { useEffect, useState } from 'react'
import {
  getDocumentDetail,
  getDocumentText,
} from '../api/documents'

type SourceViewerProps = {
  documentId: string
  chunkId?: string
  query?: string
  onClose: () => void
}

export function SourceViewer({
  documentId,
  chunkId,
  query,
  onClose,
}: SourceViewerProps) {
  const [title, setTitle] = useState(documentId)
  const [body, setBody] = useState('Loading…')
  const [meta, setMeta] = useState('')

  useEffect(() => {
    void (async () => {
      try {
        const detail = await getDocumentDetail(documentId, {
          chunk_id: chunkId,
          q: query,
        })
        setTitle(String(detail.title || documentId))
        setMeta(
          [
            detail.document_type,
            detail.matter_code || detail.matter_id,
            detail.author_name,
          ]
            .filter(Boolean)
            .map(String)
            .join(' · '),
        )
        try {
          const text = await getDocumentText(documentId, {
            chunk_id: chunkId,
            q: query,
          })
          setBody(
            String(
              text.highlight ||
                text.text ||
                text.body ||
                detail.body ||
                detail.text ||
                'No text available.',
            ),
          )
        } catch {
          setBody(String(detail.body || detail.text || 'No text available.'))
        }
      } catch {
        setBody('Could not load document source.')
      }
    })()
  }, [documentId, chunkId, query])

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <aside className="drawer" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Source viewer">
        <div className="drawer-head">
          <div>
            <h3>{title}</h3>
            <div className="metadata-xs" style={{ marginTop: 4 }}>
              {documentId}
              {meta ? ` · ${meta}` : ''}
              {chunkId ? ` · chunk ${chunkId}` : ''}
            </div>
          </div>
          <button type="button" className="button button-secondary" onClick={onClose}>
            Close
          </button>
        </div>
        <div className="drawer-body">
          <pre className="source-body">{body}</pre>
        </div>
      </aside>
    </div>
  )
}
