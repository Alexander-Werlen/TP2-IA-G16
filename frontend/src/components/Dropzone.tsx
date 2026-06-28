import { useRef, useState, type DragEvent, type ChangeEvent } from 'react'
import { Upload } from 'lucide-react'

import { Button } from '@/components/ui/button'

type Props = {
  accept?: string
  disabled?: boolean
  onFile: (file: File) => void
}

/**
 * Dropzone minimalista: click o drag&drop, con un solo archivo.
 * El componente NO sube el archivo: lo entrega al padre vía `onFile`.
 */
export default function Dropzone({
  accept = '.pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain',
  disabled = false,
  onFile,
}: Props) {
  const inputRef = useRef<HTMLInputElement | null>(null)
  const [dragOver, setDragOver] = useState(false)

  function emit(file: File | undefined | null) {
    if (!file) return
    onFile(file)
  }

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setDragOver(false)
    if (disabled) return
    emit(e.dataTransfer.files?.[0])
  }

  function onDragOver(e: DragEvent<HTMLDivElement>) {
    e.preventDefault()
    if (disabled) return
    setDragOver(true)
  }

  function onDragLeave(e: DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setDragOver(false)
  }

  function onClick() {
    if (disabled) return
    inputRef.current?.click()
  }

  function onChange(e: ChangeEvent<HTMLInputElement>) {
    emit(e.target.files?.[0])
    // reset para permitir re-subir el mismo archivo
    e.target.value = ''
  }

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onClick()
        }
      }}
      onDrop={onDrop}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      aria-disabled={disabled}
      className={[
        'rounded-lg border-2 border-dashed p-6 text-center cursor-pointer transition-colors',
        'focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2',
        disabled
          ? 'opacity-50 cursor-not-allowed bg-muted/30'
          : dragOver
          ? 'border-primary bg-primary/5'
          : 'border-muted-foreground/30 hover:border-primary/50 hover:bg-muted/20',
      ].join(' ')}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        onChange={onChange}
        disabled={disabled}
        className="sr-only"
        aria-label="Subir archivo"
      />
      <Upload className="mx-auto size-6 text-muted-foreground" />
      <p className="mt-2 text-sm font-medium">
        Arrastrá un archivo acá o hacé click para elegir
      </p>
      <p className="mt-1 text-xs text-muted-foreground">PDF, DOCX o TXT · máx. 20 MB</p>
      <Button type="button" variant="outline" size="sm" className="mt-3" tabIndex={-1}>
        Elegir archivo
      </Button>
    </div>
  )
}
