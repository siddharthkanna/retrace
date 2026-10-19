import { useState } from 'react'
import { listIncidents, listInvestigations, startInvestigation, type Incident } from './api'
import { IncidentList } from './IncidentList'
import { InvestigationView } from './InvestigationView'
import { usePolling } from './usePolling'

export default function App() {
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const incidents = usePolling(listIncidents, 'incidents', 5000)
  const selected = incidents.value?.find((incident) => incident.id === selectedId) ?? null

  return (
    <div className="app">
      <IncidentList
        incidents={incidents.value ?? []}
        selectedId={selectedId}
        onSelect={setSelectedId}
        onCreated={(incident) => {
          incidents.refresh()
          setSelectedId(incident.id)
        }}
      />
      <main className="main">
        <div className="content">
          {incidents.error && <p className="error">{incidents.error}</p>}
          {selected ? (
            <IncidentDetail incident={selected} onChanged={incidents.refresh} />
          ) : (
            <p className="muted empty">Select an incident to see its investigations.</p>
          )}
        </div>
      </main>
    </div>
  )
}

function IncidentDetail({ incident, onChanged }: { incident: Incident; onChanged: () => void }) {
  const investigations = usePolling(() => listInvestigations(incident.id), incident.id)
  const [error, setError] = useState<string | null>(null)
  const running = incident.status === 'investigating'

  async function investigate() {
    try {
      await startInvestigation(incident.id)
      setError(null)
      investigations.refresh()
      onChanged()
    } catch (problem) {
      setError((problem as Error).message)
    }
  }

  return (
    <>
      <header className="incident-head">
        <p className="muted">
          Incident #{incident.id} · {incident.severity} severity · {incident.source} ·{' '}
          {new Date(incident.created_at).toLocaleString()}
        </p>
        <h2>{incident.description}</h2>
        <button className="primary" onClick={investigate} disabled={running}>
          {running ? 'Investigating…' : 'Investigate'}
        </button>
        {(error ?? investigations.error) && (
          <p className="error">{error ?? investigations.error}</p>
        )}
      </header>
      {investigations.value?.map((investigation) => (
        <InvestigationView
          key={investigation.id}
          investigation={investigation}
          onChanged={investigations.refresh}
        />
      ))}
      {investigations.value?.length === 0 && <p className="muted empty">Not investigated yet.</p>}
    </>
  )
}
