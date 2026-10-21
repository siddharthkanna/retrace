import { useState } from 'react'
import {
  approveRecipe,
  declineRecipe,
  type Attempt,
  type Evidence,
  type Investigation,
  type Reproduction,
  type Usage,
} from './api'
import { formatDuration, formatTime } from './format'
import { Prose, StatusPill } from './parts'

type Recipe = {
  settings?: Record<string, Record<string, unknown>>
  steps?: {
    requests: { method: string; path: string; headers?: Record<string, string>; body?: unknown }[]
  }[]
  check_sql?: string
}

const LABEL = /\bE\d+\b/g

export function InvestigationView({
  investigation,
  onChanged,
}: {
  investigation: Investigation
  onChanged: () => void
}) {
  const { report, reproduction, evidence } = investigation
  const [open, setOpen] = useState<string | null>(null)
  const cited = new Set(report?.evidence ?? [])
  const ruledOut = new Set(report?.rejected_hypotheses.flatMap((text) => text.match(LABEL) ?? []))

  // Open one piece of evidence and bring it into view.
  function show(label: string) {
    setOpen(label)
    document
      .getElementById(`evidence-${label}`)
      ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }

  return (
    <article className="investigation">
      <header className="block-head">
        <h2>
          Investigation <span className="mono">#{investigation.id}</span>
        </h2>
        <StatusPill status={investigation.status} />
        <span className="muted mono">{investigation.model}</span>
        <span className="muted push">
          {investigation.finished_at
            ? `Finished ${formatTime(investigation.finished_at)}`
            : `Started ${formatTime(investigation.started_at)}`}
        </span>
      </header>

      <div className="layout">
        <div className="column">
          <section className="panel finding" aria-labelledby={`cause-${investigation.id}`}>
            {report ? (
              <>
                <h3 id={`cause-${investigation.id}`} className="label">
                  Root cause
                </h3>
                <p className="cause">
                  <Prose text={report.root_cause} />
                </p>
                <Trail evidence={evidence} cited={cited} ruledOut={ruledOut} onShow={show} />
                <div className="pair">
                  <div>
                    <h3 className="label">What happened</h3>
                    <p>
                      <Prose text={report.summary} />
                    </p>
                  </div>
                  <div>
                    <h3 className="label">Suggested fix</h3>
                    <p>
                      <Prose text={report.suggested_fix} />
                    </p>
                  </div>
                </div>
                {report.rejected_hypotheses.length > 0 && (
                  <>
                    <h3 className="label">Ruled out</h3>
                    <ul className="ruled-out">
                      {report.rejected_hypotheses.map((text) => (
                        <li key={text}>
                          <Prose text={text} />
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </>
            ) : investigation.status === 'running' ? (
              <>
                <h3 id={`cause-${investigation.id}`} className="label">
                  Root cause
                </h3>
                <p className="cause muted">
                  Gathering evidence. This page updates by itself as the agent works.
                </p>
              </>
            ) : (
              <>
                <h3 id={`cause-${investigation.id}`} className="label">
                  No report
                </h3>
                <p className="cause">
                  {investigation.failure_reason ?? 'The investigation stopped without a report.'}
                </p>
                {evidence.length > 0 && (
                  <Trail evidence={evidence} cited={cited} ruledOut={ruledOut} onShow={show} />
                )}
              </>
            )}
          </section>

          <EvidenceTable
            evidence={evidence}
            cited={cited}
            ruledOut={ruledOut}
            open={open}
            onToggle={(label) => setOpen(open === label ? null : label)}
          />
        </div>

        <div className="column">
          <ReproductionPanel
            investigationId={investigation.id}
            reproduction={reproduction}
            hasReport={Boolean(report)}
            onChanged={onChanged}
          />

          <UsagePanel usage={investigation.usage} />
        </div>
      </div>
    </article>
  )
}

// What the investigation took, as label and figure rows.
function UsagePanel({ usage }: { usage: Usage | null }) {
  const dash = <span className="muted">—</span>
  const rows: [string, React.ReactNode][] = [
    ['Model calls', usage ? usage.model_calls.toLocaleString() : dash],
    ['Tool calls', usage ? usage.tool_calls.toLocaleString() : dash],
    ['Tokens', usage ? (usage.input_tokens + usage.output_tokens).toLocaleString() : dash],
    ['Cost', usage?.cost_usd != null ? `$${usage.cost_usd.toFixed(2)}` : dash],
    ['Model time', usage ? formatDuration(usage.model_seconds) : dash],
  ]
  return (
    <section className="panel usage" aria-label="What it took">
      <header className="panel-head">
        <h3>What it took</h3>
      </header>
      <dl>
        {rows.map(([name, value]) => (
          <div key={name}>
            <dt>{name}</dt>
            <dd className="num">{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

// Every piece of evidence in the order it was gathered; the cited ones carry the hue.
function Trail({
  evidence,
  cited,
  ruledOut,
  onShow,
}: {
  evidence: Evidence[]
  cited: Set<string>
  ruledOut: Set<string>
  onShow: (label: string) => void
}) {
  const citedCount = evidence.filter((item) => cited.has(item.label)).length
  return (
    <div className="trail">
      <p className="muted">
        {cited.size
          ? `Cites ${citedCount} of the ${evidence.length} pieces of evidence gathered`
          : `${evidence.length} pieces of evidence gathered`}
        {ruledOut.size > 0 && ` · ${ruledOut.size} used to rule out another explanation`}
      </p>
      <ol style={{ '--count': Math.min(evidence.length, 12) } as React.CSSProperties}>
        {evidence.map((item) => (
          <li key={item.label}>
            <button
              className={
                cited.has(item.label) ? 'cited' : ruledOut.has(item.label) ? 'ruled' : undefined
              }
              title={`${item.label} · ${item.tool}`}
              onClick={() => onShow(item.label)}
            >
              <span className="mono">{item.label}</span>
              <span className="tool">{SHORT[item.tool] ?? item.tool}</span>
            </button>
          </li>
        ))}
      </ol>
    </div>
  )
}

// What each tool looked at, short enough for a trail cell.
const SHORT: Record<string, string> = {
  query_logs: 'logs',
  get_trace: 'trace',
  describe_db: 'tables',
  query_db: 'data',
  get_config: 'settings',
  list_commits: 'commits',
  show_commit: 'diff',
}

const VERDICT: Record<Reproduction['outcome'], string> = {
  reproduced: 'Made the failure happen again on the test copy.',
  not_reproduced: 'Could not make the failure happen again.',
  awaiting_approval: 'Waiting for your approval before it changes anything.',
  running: 'Carrying out the approved recipe.',
  declined: 'You declined the recipe. Nothing was changed.',
}

function ReproductionPanel({
  investigationId,
  reproduction,
  hasReport,
  onChanged,
}: {
  investigationId: number
  reproduction: Reproduction | null
  hasReport: boolean
  onChanged: () => void
}) {
  return (
    <section className="panel repro" aria-labelledby={`repro-${investigationId}`}>
      <header className="panel-head">
        <h3 id={`repro-${investigationId}`}>Reproduction</h3>
        {reproduction && <StatusPill status={reproduction.outcome} />}
      </header>
      {reproduction ? (
        <>
          <p className="verdict">{VERDICT[reproduction.outcome]}</p>
          {reproduction.outcome === 'awaiting_approval' && (
            <Approval investigationId={investigationId} onChanged={onChanged} />
          )}
          {reproduction.attempts.length > 0 && (
            <ul className="attempts">
              {reproduction.attempts.map((attempt, index) => (
                <li key={index}>
                  <span>Recipe {index + 1}</span>
                  <StatusPill status={attempt.result.outcome} />
                  <p className="muted">{attempt.result.detail}</p>
                </li>
              ))}
            </ul>
          )}
          {reproduction.attempts.length === 0 && reproduction.outcome === 'not_reproduced' && (
            <p className="muted">The agent did not write a recipe.</p>
          )}
          <RecipeDetails reproduction={reproduction} />
        </>
      ) : (
        <p className="muted">
          {hasReport
            ? 'Not tried. Reproduction needs TARGET_API_URL and a database in .env.'
            : 'Tried only after a report is accepted.'}
        </p>
      )}
    </section>
  )
}

function Approval({
  investigationId,
  onChanged,
}: {
  investigationId: number
  onChanged: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function settle(action: (id: number) => Promise<unknown>) {
    setBusy(true)
    try {
      await action(investigationId)
      setError(null)
      onChanged()
    } catch (problem) {
      setError((problem as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="approval">
      <p>The recipe below changes settings and sends requests to the test copy of the system.</p>
      <div className="actions">
        <button className="primary" disabled={busy} onClick={() => settle(approveRecipe)}>
          Approve and run
        </button>
        <button className="secondary" disabled={busy} onClick={() => settle(declineRecipe)}>
          Decline
        </button>
      </div>
      {error && <p className="notice error">{error}</p>}
    </div>
  )
}

// The recipe to approve, or the last one carried out, written out as what it will do.
function RecipeDetails({ reproduction }: { reproduction: Reproduction }) {
  const last: Attempt | undefined = reproduction.attempts.at(-1)
  const recipe = (
    reproduction.outcome === 'awaiting_approval' ? reproduction.pending : last?.recipe
  ) as Recipe | undefined
  if (!recipe) return null
  const waiting = reproduction.outcome === 'awaiting_approval'
  const replies = waiting ? [] : (last?.result.replies ?? [])
  const settings = Object.entries(recipe.settings ?? {}).flatMap(([source, values]) =>
    Object.entries(values).map(([name, value]) => ({ source, name, value })),
  )

  return (
    // Open while it waits for approval; folded away once it has run.
    <details className="recipe" open={waiting}>
      <summary>{waiting ? 'The recipe to approve' : 'Show the recipe it ran'}</summary>
      <div className="recipe-parts">
        <div>
          <h4 className="label">Settings it changes</h4>
          {settings.length ? (
            <ul className="settings">
              {settings.map(({ source, name, value }) => (
                <li key={`${source}.${name}`}>
                  <code>{name}</code> → <code>{JSON.stringify(value)}</code>
                  <span className="muted"> on {source}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">None.</p>
          )}
        </div>
        <div>
          <h4 className="label">Requests it sends</h4>
          <ol className="steps">
            {recipe.steps?.map((step, index) => (
              <li key={index}>
                {step.requests.length > 1 && (
                  <p className="muted">{step.requests.length} requests at the same moment</p>
                )}
                {step.requests.map((request, position) => (
                  <div key={position} className="request">
                    <code className="call">
                      {request.method} {request.path}
                    </code>
                    {request.body != null && <code className="body">{compact(request.body)}</code>}
                    {replies[index]?.[position] && (
                      <code className="reply">{replies[index][position]}</code>
                    )}
                  </div>
                ))}
              </li>
            ))}
          </ol>
        </div>
        <div>
          <h4 className="label">How it checks</h4>
          <p className="muted">Rows before the requests: none. Rows after: at least one.</p>
          <pre>{recipe.check_sql}</pre>
        </div>
      </div>
      <details className="raw">
        <summary>Show the recipe as JSON</summary>
        <pre>{JSON.stringify(recipe, null, 2)}</pre>
      </details>
    </details>
  )
}

function EvidenceTable({
  evidence,
  cited,
  ruledOut,
  open,
  onToggle,
}: {
  evidence: Evidence[]
  cited: Set<string>
  ruledOut: Set<string>
  open: string | null
  onToggle: (label: string) => void
}) {
  return (
    <section className="panel evidence" aria-label="Evidence">
      <header className="panel-head">
        <h3>Evidence</h3>
        <span className="muted">
          {evidence.length === 1 ? '1 tool result' : `${evidence.length} tool results`}, in the
          order the agent asked for them
        </span>
      </header>
      {evidence.length === 0 ? (
        <p className="empty">No evidence gathered yet.</p>
      ) : (
        <div className="rows" role="list">
          <div className="row head" aria-hidden="true">
            <span>Label</span>
            <span>Tool</span>
            <span>Request</span>
            <span>Used in report</span>
          </div>
          {evidence.map((item) => (
            <div key={item.label} id={`evidence-${item.label}`} role="listitem" className="item">
              <button
                className={open === item.label ? 'row open' : 'row'}
                aria-expanded={open === item.label}
                onClick={() => onToggle(item.label)}
              >
                <span className="mono">{item.label}</span>
                <span className="mono">{item.tool}</span>
                <span className="request-text">{describe(item.arguments)}</span>
                <span>
                  {cited.has(item.label) ? (
                    <span className="cited-mark">Cited</span>
                  ) : ruledOut.has(item.label) ? (
                    'Ruled out'
                  ) : (
                    <span className="muted">—</span>
                  )}
                </span>
              </button>
              {open === item.label && <pre className="result">{pretty(item.result)}</pre>}
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

// A tool's inputs as one readable line: contains "order-ab19b4e6".
function describe(args: Record<string, unknown>) {
  const parts = Object.entries(args).map(
    ([name, value]) =>
      `${name.replace('_', ' ')} ${typeof value === 'string' ? `"${value}"` : JSON.stringify(value)}`,
  )
  return parts.join(' · ') || 'no inputs'
}

function compact(value: unknown) {
  return JSON.stringify(value).replace(/","/g, '", "').replace(/,"/g, ', "')
}

// Tool results are JSON text; show them indented when they parse, as they are when cut short.
function pretty(text: string): string {
  try {
    return JSON.stringify(JSON.parse(text), null, 2)
  } catch {
    return text
  }
}
