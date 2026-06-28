import { useCallback, useEffect, useState } from 'react'

const STORAGE_PREFIX = 'tutoria:sidenav:'

function loadSet(key: string): Set<number> {
  if (typeof window === 'undefined') return new Set()
  try {
    const raw = window.localStorage.getItem(STORAGE_PREFIX + key)
    if (!raw) return new Set()
    const parsed = JSON.parse(raw) as unknown
    if (Array.isArray(parsed)) {
      return new Set(parsed.filter((n): n is number => Number.isFinite(n)))
    }
  } catch {
    /* ignore */
  }
  return new Set()
}

function saveSet(key: string, set: Set<number>) {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(STORAGE_PREFIX + key, JSON.stringify([...set]))
  } catch {
    /* ignore */
  }
}

type Updater = (prev: Set<number>) => Set<number>

export function usePersistedSet(key: string): [Set<number>, (updater: Updater) => void] {
  const [set, setSet] = useState<Set<number>>(() => loadSet(key))

  useEffect(() => {
    saveSet(key, set)
  }, [key, set])

  const update = useCallback((updater: Updater) => {
    setSet((prev) => updater(prev))
  }, [])

  return [set, update]
}
