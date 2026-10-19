// The shapes the investigator's API returns, and the calls the viewer makes.

export type Incident = {
  id: number
  description: string
  severity: 'low' | 'medium' | 'high' | 'critical'
  status: 'open' | 'investigating' | 'resolved' | 'failed'
  source: string
  created_at: string
}

export type Report = {
  summary: string
  root_cause: string
  evidence: string[]
  rejected_hypotheses: string[]
  suggested_fix: string
}

export type Evidence = {
  label: string
  tool: string
  arguments: Record<string, unknown>
  result: string
}

export type Attempt = {
  recipe: Record<string, unknown>
  result: {
    outcome: 'reproduced' | 'not_reproduced' | 'invalid_recipe'
    detail: string
    replies: string[][]
  }
}

export type Reproduction = {
  outcome: 'reproduced' | 'not_reproduced' | 'awaiting_approval' | 'running' | 'declined'
  attempts: Attempt[]
  // The recipe waiting for approval, or the one that was declined.
  pending: Record<string, unknown> | null
}

export type Usage = {
  model_calls: number
  tool_calls: number
  input_tokens: number
  output_tokens: number
  model_seconds: number
  cost_usd: number | null
}

export type Investigation = {
  id: number
  incident_id: number
  model: string
  status: 'running' | 'resolved' | 'failed'
  failure_reason: string | null
  report: Report | null
  evidence: Evidence[]
  reproduction: Reproduction | null
  usage: Usage | null
  started_at: string
  finished_at: string | null
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, init)
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail ?? `The request failed (${response.status}).`)
  }
  return response.json()
}

export const listIncidents = () => call<Incident[]>('/incidents?limit=100')

export const listInvestigations = (incidentId: number) =>
  call<Investigation[]>(`/incidents/${incidentId}/investigations`)

export const startInvestigation = (incidentId: number) =>
  call<Investigation>(`/incidents/${incidentId}/investigate`, {
    method: 'POST',
  })

export const createIncident = (description: string, severity: Incident['severity']) =>
  call<Incident>('/incidents', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ description, severity }),
  })

export const approveRecipe = (investigationId: number) =>
  call<Investigation>(`/investigations/${investigationId}/approve`, { method: 'POST' })

export const declineRecipe = (investigationId: number) =>
  call<Investigation>(`/investigations/${investigationId}/decline`, { method: 'POST' })
