import { useRef, useState } from 'react'
import { createIncident, type Incident } from './api'
import { formatAgo } from './format'

type Props = {
  incidents: Incident[]
  selectedId: number | null
  onSelect: (id: number) => void
  onCreated: (incident: Incident) => void
}

// Incidents waiting for a first look come first; investigated ones follow.
const GROUPS: [string, Incident['status'][]][] = [
  ['To investigate', ['open', 'investigating']],
  ['Investigated', ['resolved', 'failed']],
]

export function IncidentList({ incidents, selectedId, onSelect, onCreated }: Props) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <Mark />
        <span>Retrace</span>
      </div>
      <NewIncident onCreated={onCreated} />
      <nav className="incidents" aria-label="Incidents">
        {GROUPS.map(([title, statuses]) => {
          const items = incidents.filter((incident) => statuses.includes(incident.status))
          if (!items.length) return null
          return (
            <section key={title} className="group">
              <h2>
                {title} <span className="num">{items.length}</span>
              </h2>
              <ul>
                {items.map((incident) => (
                  <li key={incident.id}>
                    <button
                      className={incident.id === selectedId ? 'incident selected' : 'incident'}
                      aria-current={incident.id === selectedId ? 'page' : undefined}
                      onClick={() => onSelect(incident.id)}
                    >
                      <span className="incident-text">{incident.description}</span>
                      <span className="incident-meta">
                        <span className={`dot ${incident.status}`}>{incident.status}</span>
                        <span>
                          <span className="mono">#{incident.id}</span> ·{' '}
                          {formatAgo(incident.created_at)}
                        </span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )
        })}
        {incidents.length === 0 && (
          <p className="empty">No incidents yet. Report one with New incident.</p>
        )}
      </nav>
    </aside>
  )
}

// Retrace's mark: a path that loops back on itself, in the accent.
function Mark() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden="true">
      <path
        d="M4 16V8a4 4 0 0 1 4-4h5a3 3 0 0 1 0 6H8l3 3"
        fill="none"
        stroke="var(--accent)"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

// A native modal dialog: it traps focus, closes on Escape and dims the page behind it.
function NewIncident({ onCreated }: { onCreated: (incident: Incident) => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [description, setDescription] = useState('')
  const [severity, setSeverity] = useState<Incident['severity']>('medium')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    try {
      onCreated(await createIncident(description, severity))
      setDescription('')
      setSeverity('medium')
      setError(null)
      dialog.current?.close()
    } catch (problem) {
      setError((problem as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <button className="secondary new-incident" onClick={() => dialog.current?.showModal()}>
        <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
          <path d="M7 2v10M2 7h10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
        New incident
      </button>
      <dialog
        ref={dialog}
        className="dialog"
        aria-labelledby="new-incident-title"
        // A click on the dimmed backdrop lands on the dialog itself, not on its form.
        onClick={(event) => event.target === dialog.current && dialog.current.close()}
      >
        <form onSubmit={submit}>
          <h2 id="new-incident-title">New incident</h2>
          <p className="muted">
            Describe what went wrong. Retrace searches the logs for any ID you include.
          </p>
          <label>
            What went wrong
            <textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="For example: Finance found 60.00 refunded against a 30.00 payment for order order-ab19b4e6."
              rows={5}
              required
              autoFocus
            />
          </label>
          <label>
            Severity
            <select
              value={severity}
              onChange={(event) => setSeverity(event.target.value as Incident['severity'])}
            >
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
              <option value="critical">Critical</option>
            </select>
          </label>
          {error && <p className="notice error">{error}</p>}
          <div className="dialog-actions">
            <button type="button" className="secondary" onClick={() => dialog.current?.close()}>
              Cancel
            </button>
            <button className="primary" type="submit" disabled={busy}>
              {busy ? 'Reporting…' : 'Report incident'}
            </button>
          </div>
        </form>
      </dialog>
    </>
  )
}
