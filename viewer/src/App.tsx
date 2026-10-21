import { useEffect, useState } from 'react'
import { listIncidents, listInvestigations, startInvestigation, type Incident } from './api'
import { IncidentList } from './IncidentList'
import { InvestigationView } from './InvestigationView'
import { formatTime } from './format'
import { StatusPill } from './parts'
import { usePolling } from './usePolling'

// The chosen incident lives in the address (#/incidents/22), so a reload or a shared link keeps it.
function useSelectedIncident() {
  const read = () => Number(/^#\/incidents\/(\d+)$/.exec(window.location.hash)?.[1]) || null
  const [id, setId] = useState(read)
  useEffect(() => {
    const follow = () => setId(read())
    window.addEventListener('hashchange', follow)
    return () => window.removeEventListener('hashchange', follow)
  }, [])
  const select = (next: number) => {
    window.location.hash = `/incidents/${next}`
  }
  return [id, select] as const
}

export default function App() {
  const [selectedId, select] = useSelectedIncident()
  const [menuOpen, setMenuOpen] = useState(false)
  const incidents = usePolling(listIncidents, 'incidents', 5000)
  const selected = incidents.value?.find((incident) => incident.id === selectedId) ?? null

  function choose(id: number) {
    select(id)
    setMenuOpen(false)
  }

  return (
    <div className={menuOpen ? 'shell menu-open' : 'shell'}>
      <IncidentList
        incidents={incidents.value ?? []}
        selectedId={selectedId}
        onSelect={choose}
        onCreated={(incident) => {
          incidents.refresh()
          choose(incident.id)
        }}
      />
      <header className="topbar">
        <button
          className="menu-button"
          aria-expanded={menuOpen}
          aria-label={menuOpen ? 'Close the incident list' : 'Open the incident list'}
          onClick={() => setMenuOpen(!menuOpen)}
        >
          <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
            <path d="M3 5h12M3 9h12M3 13h12" stroke="currentColor" strokeWidth="1.5" />
          </svg>
        </button>
        <nav className="crumbs" aria-label="Breadcrumb">
          <span>Incidents</span>
          {selected && (
            <>
              <span aria-hidden="true">/</span>
              <span className="mono">#{selected.id}</span>
              <StatusPill status={selected.status} />
            </>
          )}
        </nav>
      </header>
      <main className="sheet">
        {incidents.error && (
          <p className="notice error">
            Couldn't reach the investigator: {incidents.error} Retrying every few seconds.
          </p>
        )}
        {selected ? (
          <IncidentDetail incident={selected} onChanged={incidents.refresh} />
        ) : (
          <div className="blank">
            <h1>Incidents</h1>
            <p className="muted">
              Choose an incident from the list, or report a new one with New incident.
            </p>
          </div>
        )}
      </main>
    </div>
  )
}

function IncidentDetail({ incident, onChanged }: { incident: Incident; onChanged: () => void }) {
  const investigations = usePolling(() => listInvestigations(incident.id), incident.id)
  const [chosen, setChosen] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const running = incident.status === 'investigating'
  const list = (investigations.value ?? []).filter((item) => item.incident_id === incident.id)
  // The newest investigation is shown unless another one was chosen.
  const shown = list.find((item) => item.id === chosen) ?? list[0]

  async function investigate() {
    try {
      await startInvestigation(incident.id)
      setError(null)
      setChosen(null)
      investigations.refresh()
      onChanged()
    } catch (problem) {
      setError((problem as Error).message)
    }
  }

  return (
    <>
      <header className="title-row">
        <div>
          <h1>{incident.description}</h1>
          <p className="muted">
            {capitalise(incident.severity)} severity ·{' '}
            {incident.source === 'watcher' ? 'raised by the watcher' : 'reported'}{' '}
            {formatTime(incident.created_at)} ·{' '}
            {list.length === 1 ? '1 investigation' : `${list.length} investigations`}
          </p>
        </div>
        {/* The primary action until there is a report; after that, approving a recipe is. */}
        <button
          className={list.length ? 'secondary' : 'primary'}
          onClick={investigate}
          disabled={running}
        >
          {running ? 'Investigating…' : list.length ? 'Investigate again' : 'Investigate'}
        </button>
      </header>
      {(error ?? investigations.error) && (
        <p className="notice error">{error ?? investigations.error}</p>
      )}

      {list.length > 1 && (
        <div className="tabs" role="tablist" aria-label="Investigations">
          {list.map((item) => (
            <button
              key={item.id}
              role="tab"
              aria-selected={item.id === shown?.id}
              onClick={() => setChosen(item.id)}
            >
              Investigation <span className="mono">#{item.id}</span>
              <span className="muted">{item.status}</span>
            </button>
          ))}
        </div>
      )}

      {shown ? (
        <InvestigationView
          key={shown.id}
          investigation={shown}
          onChanged={investigations.refresh}
        />
      ) : (
        investigations.value && (
          <p className="empty">
            Not investigated yet. Investigate reads the logs, traces, database and settings, then
            writes a report that cites what it found.
          </p>
        )
      )}
    </>
  )
}

const capitalise = (text: string) => text.charAt(0).toUpperCase() + text.slice(1)
