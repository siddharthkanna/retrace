// How times and durations are written on the page.

export const formatTime = (iso: string) =>
  new Date(iso).toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })

export function formatDuration(seconds: number) {
  const whole = Math.round(seconds)
  return whole < 60 ? `${whole} s` : `${Math.floor(whole / 60)} m ${whole % 60} s`
}

// How long ago, for lists: "just now", "12 min", "3 h", then the date.
export function formatAgo(iso: string) {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} min`
  if (minutes < 24 * 60) return `${Math.round(minutes / 60)} h`
  return new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
}
