import { useState } from 'react'
import { createIncident, type Incident } from './api'

type Props = {
  incidents: Incident[]
  selectedId: number | null
  onSelect: (id: number) => void
  onCreated: (incident: Incident) => void
}

export function IncidentList({ incidents, selectedId, onSelect, onCreated }: Props) {
  return (
    <aside className="sidebar">
      <h1 className="brand">Retrace</h1>
      <NewIncident onCreated={onCreated} />
      <ul className="incidents">
        {incidents.map((incident) => (
          <li key={incident.id}>
            <button
              className={incident.id === selectedId ? 'incident selected' : 'incident'}
              onClick={() => onSelect(incident.id)}
            >
              <span className="incident-text">{incident.description}</span>
              <span className="incident-meta">
                <span className="muted">#{incident.id}</span>
                <span className={`badge ${incident.status}`}>{incident.status}</span>
              </span>
            </button>
          </li>
        ))}
        {incidents.length === 0 && <li className="muted empty">No incidents yet.</li>}
      </ul>
    </aside>
  )
}

function NewIncident({ onCreated }: { onCreated: (incident: Incident) => void }) {
  const [description, setDescription] = useState('')
  const [severity, setSeverity] = useState<Incident['severity']>('medium')
  const [error, setError] = useState<string | null>(null)

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    try {
      onCreated(await createIncident(description, severity))
      setDescription('')
      setError(null)
    } catch (problem) {
      setError((problem as Error).message)
    }
  }

  return (
    <details className="new-incident">
      <summary>New incident</summary>
      <form onSubmit={submit}>
        <textarea
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          placeholder="Describe what went wrong…"
          aria-label="Incident description"
          rows={3}
          required
        />
        <div className="row">
          <select
            value={severity}
            onChange={(event) => setSeverity(event.target.value as Incident['severity'])}
            aria-label="Severity"
          >
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
            <option value="critical">Critical</option>
          </select>
          <button className="primary" type="submit">
            Report
          </button>
        </div>
        {error && <p className="error">{error}</p>}
      </form>
    </details>
  )
}
