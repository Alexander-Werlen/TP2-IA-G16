import { useEffect, useState, type FormEvent, type ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

type Props = {
  open: boolean
  title: string
  description?: string
  label: string
  placeholder?: string
  submitText?: string
  initialValue?: string
  onCancel: () => void
  onSubmit: (value: string) => Promise<void> | void
}

export default function NameDialog({
  open,
  title,
  description,
  label,
  placeholder,
  submitText = 'Crear',
  initialValue = '',
  onCancel,
  onSubmit,
}: Props) {
  const [value, setValue] = useState(initialValue)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (open) {
      setValue(initialValue)
      setError(null)
      setLoading(false)
    }
  }, [open, initialValue])

  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape' && !loading) onCancel()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, loading, onCancel])

  if (!open) return null

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const v = value.trim()
    if (!v) {
      setError('El nombre no puede estar vacío')
      return
    }
    setError(null)
    setLoading(true)
    try {
      await onSubmit(v)
    } catch (err) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(detail ?? 'No se pudo completar la acción')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !loading) onCancel()
      }}
    >
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm rounded-lg border bg-background shadow-lg"
      >
        <div className="p-4 space-y-1 border-b">
          <h2 className="text-base font-semibold">{title}</h2>
          {description && <p className="text-sm text-muted-foreground">{description}</p>}
        </div>
        <div className="p-4 space-y-2">
          <Label htmlFor="name-dialog-input">{label}</Label>
          <Input
            id="name-dialog-input"
            autoFocus
            value={value}
            placeholder={placeholder}
            onChange={(e) => setValue(e.target.value)}
            disabled={loading}
          />
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
        </div>
        <div className="p-4 border-t flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={onCancel} disabled={loading}>
            Cancelar
          </Button>
          <Button type="submit" disabled={loading}>
            {loading ? 'Guardando…' : submitText}
          </Button>
        </div>
      </form>
    </div>
  )
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmText = 'Eliminar',
  cancelText = 'Cancelar',
  destructive = true,
  onCancel,
  onConfirm,
}: {
  open: boolean
  title: string
  description?: ReactNode
  confirmText?: string
  cancelText?: string
  destructive?: boolean
  onCancel: () => void
  onConfirm: () => Promise<void> | void
}) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      setLoading(false)
      setError(null)
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape' && !loading) onCancel()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, loading, onCancel])

  if (!open) return null

  async function handleConfirm() {
    setError(null)
    setLoading(true)
    try {
      await onConfirm()
    } catch (err) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(detail ?? 'No se pudo completar la acción')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !loading) onCancel()
      }}
    >
      <div className="w-full max-w-sm rounded-lg border bg-background shadow-lg">
        <div className="p-4 space-y-1 border-b">
          <h2 className="text-base font-semibold">{title}</h2>
          {description && <div className="text-sm text-muted-foreground">{description}</div>}
        </div>
        {error && (
          <p role="alert" className="px-4 pt-3 text-sm text-destructive">
            {error}
          </p>
        )}
        <div className="p-4 flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={onCancel} disabled={loading}>
            {cancelText}
          </Button>
          <Button
            type="button"
            variant={destructive ? 'destructive' : 'default'}
            onClick={handleConfirm}
            disabled={loading}
          >
            {loading ? 'Eliminando…' : confirmText}
          </Button>
        </div>
      </div>
    </div>
  )
}
