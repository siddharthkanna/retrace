import { useEffect, useState } from 'react'

// Loads a value now and again every few seconds, so the page follows a running
// investigation without a refresh. `key` restarts it when what is loaded changes.
export function usePolling<T>(load: () => Promise<T>, key: unknown, everyMs = 3000) {
  const [value, setValue] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    let current = true
    const refresh = () =>
      load()
        .then((loaded) => {
          if (!current) return
          setValue(loaded)
          setError(null)
        })
        .catch((problem: Error) => current && setError(problem.message))
    refresh()
    const timer = setInterval(refresh, everyMs)
    return () => {
      current = false
      clearInterval(timer)
    }
    // `load` is a new function on every render; `key` says when it really changed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, tick, everyMs])

  return { value, error, refresh: () => setTick((n) => n + 1) }
}
