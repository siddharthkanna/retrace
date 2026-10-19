import { useState } from 'react'
import {
  approveRecipe,
  declineRecipe,
  type Attempt,
  type Evidence,
  type Investigation,
  type Usage,
} from './api'

export function InvestigationView({
  investigation,
  onChanged,
}: {
  investigation: Investigation
  onChanged: () => void
}) {
  const { report, reproduction } = investigation
  return (
    <article className="investigation">
      <header className="row spread">
        <h3>
          Investigation #{investigation.id} <span className="muted">{investigation.model}</span>
        </h3>
        <span className={`badge ${investigation.status}`}>{investigation.status}</span>
      </header>

      {investigation.usage && <UsageLine usage={investigation.usage} />}
      {investigation.status === 'running' && (
        <p className="muted note">The agent is gathering evidence. This page updates by itself.</p>
      )}
      {investigation.failure_reason && <p className="error">{investigation.failure_reason}</p>}

      {report && (
        <section>
          <Field title="Root cause" text={report.root_cause} prominent />
          <Field title="Summary" text={report.summary} />
          <Field title="Suggested fix" text={report.suggested_fix} />
          <h4>Supporting evidence</h4>
          <p>
            {report.evidence.map((label) => (
              <a key={label} className="chip" href={`#${investigation.id}-${label}`}>
                {label}
              </a>
            ))}
          </p>
          {report.rejected_hypotheses.length > 0 && (
            <>
              <h4>Explanations ruled out</h4>
              <ul>
                {report.rejected_hypotheses.map((hypothesis) => (
                  <li key={hypothesis}>{hypothesis}</li>
                ))}
              </ul>
            </>
          )}
        </section>
      )}

      {reproduction && (
        <section>
          <h4>
            Reproduction
            <span className={`badge ${reproduction.outcome}`}>
              {reproduction.outcome.replace('_', ' ')}
            </span>
          </h4>
          {reproduction.outcome === 'awaiting_approval' && reproduction.pending && (
            <Approval
              investigationId={investigation.id}
              recipe={reproduction.pending}
              onChanged={onChanged}
            />
          )}
          {reproduction.outcome === 'running' && (
            <p className="muted">Carrying out the approved recipe. This page updates by itself.</p>
          )}
          {reproduction.attempts.length === 0 && reproduction.outcome !== 'awaiting_approval' && (
            <p className="muted">The agent did not write a recipe.</p>
          )}
          {reproduction.attempts.map((attempt, index) => (
            <AttemptView key={index} number={index + 1} attempt={attempt} />
          ))}
        </section>
      )}

      {investigation.evidence.length > 0 && (
        <section>
          <h4>Evidence gathered</h4>
          {investigation.evidence.map((item) => (
            <EvidenceView key={item.label} id={`${investigation.id}-${item.label}`} item={item} />
          ))}
        </section>
      )}
    </article>
  )
}

// The recipe the agent wants to carry out, held until a person approves or declines it.
function Approval({
  investigationId,
  recipe,
  onChanged,
}: {
  investigationId: number
  recipe: Record<string, unknown>
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
      <p>
        The agent wants to carry out this recipe. It changes the settings and sends these requests
        to the test copy of the system.
      </p>
      <pre>{JSON.stringify(recipe, null, 2)}</pre>
      <div className="row">
        <button className="primary" disabled={busy} onClick={() => settle(approveRecipe)}>
          Approve
        </button>
        <button className="secondary" disabled={busy} onClick={() => settle(declineRecipe)}>
          Decline
        </button>
      </div>
      {error && <p className="error">{error}</p>}
    </div>
  )
}

// What the investigation took, for example "14 model calls · 52,000 tokens · $0.08 · 3 min".
function UsageLine({ usage }: { usage: Usage }) {
  const tokens = usage.input_tokens + usage.output_tokens
  const parts = [
    `${usage.model_calls} model calls`,
    `${usage.tool_calls} tool calls`,
    `${tokens.toLocaleString()} tokens`,
    usage.cost_usd === null ? null : `$${usage.cost_usd.toFixed(2)}`,
    `${Math.round(usage.model_seconds)} s thinking`,
  ]
  return <p className="muted note">{parts.filter(Boolean).join(' · ')}</p>
}

function Field({ title, text, prominent }: { title: string; text: string; prominent?: boolean }) {
  return (
    <>
      <h4>{title}</h4>
      <p className={prominent ? 'prominent' : undefined}>{text}</p>
    </>
  )
}

function AttemptView({ number, attempt }: { number: number; attempt: Attempt }) {
  const { outcome, detail, replies } = attempt.result
  return (
    <details className="block">
      <summary>
        <span>Recipe {number}</span>
        <span className={`badge ${outcome}`}>{outcome.replace('_', ' ')}</span>
        <span className="muted">{detail}</span>
      </summary>
      {replies.length > 0 && (
        <>
          <h5>What the system replied</h5>
          <ol>
            {replies.map((step, index) => (
              <li key={index}>
                {step.map((reply, position) => (
                  <code key={position} className="reply">
                    {reply}
                  </code>
                ))}
              </li>
            ))}
          </ol>
        </>
      )}
      <h5>The recipe</h5>
      <pre>{JSON.stringify(attempt.recipe, null, 2)}</pre>
    </details>
  )
}

function EvidenceView({ id, item }: { id: string; item: Evidence }) {
  return (
    <details className="block" id={id}>
      <summary>
        <span className="chip">{item.label}</span>
        <code>{item.tool}</code>
        <span className="muted">{JSON.stringify(item.arguments)}</span>
      </summary>
      <pre>{pretty(item.result)}</pre>
    </details>
  )
}

// Tool results are JSON text; show them indented when they parse, as they are when cut short.
function pretty(text: string): string {
  try {
    return JSON.stringify(JSON.parse(text), null, 2)
  } catch {
    return text
  }
}
