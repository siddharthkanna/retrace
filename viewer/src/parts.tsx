// Small pieces every screen part uses: status pills, and text with `code` in it.

const TONES: Record<string, string> = {
  resolved: 'positive',
  reproduced: 'positive',
  failed: 'negative',
  invalid_recipe: 'negative',
  awaiting_approval: 'warning',
  investigating: 'neutral',
  running: 'neutral',
  open: 'neutral',
  not_reproduced: 'neutral',
  declined: 'neutral',
}

export function StatusPill({ status }: { status: string }) {
  return <span className={`pill ${TONES[status] ?? 'neutral'}`}>{status.replace('_', ' ')}</span>
}

// The agent writes setting names between backticks; show them as code.
export function Prose({ text }: { text: string }) {
  return (
    <>
      {text
        .split(/`([^`]+)`/)
        .map((part, index) => (index % 2 ? <code key={index}>{part}</code> : part))}
    </>
  )
}
