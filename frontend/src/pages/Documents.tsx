import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FileText, Loader2, Trash2, UploadCloud } from 'lucide-react'

import Dropzone from '@/components/Dropzone'
import { ConfirmDialog } from '@/components/NameDialog'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  deleteDocument,
  getCarrera,
  listDocuments,
  listModulos,
  uploadDocument,
  type Carrera,
  type Document as Doc,
  type Modulo,
} from '@/lib/api'

const POLL_INTERVAL_MS = 1500
const POLL_MAX_MS = 30_000

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString('es-AR', {
      dateStyle: 'short',
      timeStyle: 'short',
    })
  } catch {
    return iso
  }
}

function StatusBadge({ status }: { status: string }) {
  const base = 'inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider'
  if (status === 'ready') {
    return <span className={`${base} border-green-600/40 bg-green-50 text-green-700`}>✓ Listo</span>
  }
  if (status === 'processing') {
    return <span className={`${base} border-blue-600/40 bg-blue-50 text-blue-700`}>⏳ Procesando</span>
  }
  if (status === 'error') {
    return <span className={`${base} border-destructive/40 bg-destructive/10 text-destructive`}>✕ Error</span>
  }
  return <span className={base}>{status}</span>
}

export default function DocumentsPage() {
  const params = useParams()
  const qc = useQueryClient()

  const moduloId = Number(params.moduloId)
  const validModuloId = Number.isFinite(moduloId) && moduloId > 0

  const carreraQuery = useQuery<Carrera>({
    queryKey: ['carrera'],
    queryFn: getCarrera,
  })
  const modulosQuery = useQuery({
    queryKey: ['modulos'],
    queryFn: () => listModulos(),
  })
  const documentsQuery = useQuery({
    queryKey: ['documents', moduloId],
    queryFn: () => listDocuments(moduloId),
    enabled: validModuloId,
    refetchInterval: (query) => {
      const data = query.state.data
      if (!data) return false
      const hasProcessing = data.items.some((d) => d.status === 'processing')
      return hasProcessing ? POLL_INTERVAL_MS : false
    },
  })

  const [progress, setProgress] = useState<number | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [toDelete, setToDelete] = useState<Doc | null>(null)
  const [slowNoticeShown, setSlowNoticeShown] = useState(false)

  const uploadMut = useMutation({
    mutationFn: (file: File) => uploadDocument(moduloId, file, setProgress),
    onSuccess: () => {
      setProgress(null)
      setUploadError(null)
      void qc.invalidateQueries({ queryKey: ['documents', moduloId] })
    },
    onError: (err: Error) => {
      setProgress(null)
      setUploadError(err.message)
    },
  })

  const deleteMut = useMutation({
    mutationFn: (id: number) => deleteDocument(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['documents', moduloId] })
      setToDelete(null)
    },
  })

  const breadcrumb = useMemo(() => {
    if (!carreraQuery.data || !modulosQuery.data) return null
    const modulo: Modulo | undefined = modulosQuery.data.items.find(
      (m) => m.id === moduloId,
    )
    if (!modulo) return null
    const year = carreraQuery.data.years.find(
      (y) => y.year === modulo.materia_year,
    )
    if (!year) return null
    return {
      year: year.name,
      materia: modulo.materia_name,
      modulo: modulo.name,
    }
  }, [carreraQuery.data, modulosQuery.data, moduloId])

  // Aviso si el procesamiento tarda más de lo normal.
  const processingStartedAt = useRef<number | null>(null)
  useEffect(() => {
    const data = documentsQuery.data
    const hasProcessing = data?.items.some((d) => d.status === 'processing') ?? false
    if (hasProcessing && processingStartedAt.current === null) {
      processingStartedAt.current = Date.now()
    } else if (!hasProcessing) {
      processingStartedAt.current = null
      setSlowNoticeShown(false)
    }
    if (
      hasProcessing &&
      processingStartedAt.current !== null &&
      Date.now() - processingStartedAt.current > POLL_MAX_MS &&
      !slowNoticeShown
    ) {
      setSlowNoticeShown(true)
    }
  }, [documentsQuery.data, slowNoticeShown])

  if (!validModuloId) {
    return (
      <div className="flex-1 flex items-center justify-center p-4">
        <p className="text-sm text-destructive">Módulo inválido.</p>
      </div>
    )
  }

  const loading =
    documentsQuery.isLoading || carreraQuery.isLoading || modulosQuery.isLoading
  const documents = documentsQuery.data?.items ?? []
  const modulo = modulosQuery.data?.items.find((m) => m.id === moduloId)

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <header className="border-b shrink-0">
        <div className="px-4 py-3 flex items-center gap-3">
          <div className="flex-1 min-w-0">
            <h1 className="text-base font-semibold truncate">
              {modulo?.name ?? (modulosQuery.isLoading ? 'Cargando…' : 'Documentos')}
            </h1>
            {breadcrumb && (
              <p className="text-xs text-muted-foreground truncate">
                {breadcrumb.year} · {breadcrumb.materia} · {breadcrumb.modulo}
              </p>
            )}
          </div>
        </div>
      </header>

      <section className="flex-1 min-h-0 overflow-y-auto px-4 py-6 max-w-3xl w-full mx-auto space-y-6">
        <Card>
          <CardHeader>
            <CardTitle>Subir material</CardTitle>
            <CardDescription>
              PDF, DOCX o TXT. El archivo se procesa en segundo plano (parseo,
               chunks y resumen con LLM).
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Dropzone
              disabled={uploadMut.isPending}
              onFile={(file) => {
                setUploadError(null)
                setProgress(0)
                uploadMut.mutate(file)
              }}
            />
            {progress !== null && (
              <div className="space-y-1">
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <UploadCloud className="size-3" />
                  Subiendo… {progress}%
                </div>
                <div className="h-1.5 w-full overflow-hidden rounded bg-muted">
                  <div
                    className="h-full bg-primary transition-all"
                    style={{ width: `${progress}%` }}
                  />
                </div>
              </div>
            )}
            {uploadError && (
              <p role="alert" className="text-sm text-destructive">
                {uploadError}
              </p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Documentos del módulo</CardTitle>
            <CardDescription>
              {loading
                ? 'Cargando…'
                : documents.length === 0
                ? 'Aún no subiste archivos.'
                : `${documents.length} archivo${documents.length === 1 ? '' : 's'}`}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {documentsQuery.error && (
              <p className="text-sm text-destructive mb-3">
                No se pudo cargar la lista de documentos.
              </p>
            )}
            {slowNoticeShown && (
              <p className="text-xs text-muted-foreground mb-3">
                El procesamiento está tardando más de lo normal.
                estar saturado; recargá la página en unos segundos.
              </p>
            )}
            <ul className="space-y-3">
              {documents.map((doc) => (
                <li
                  key={doc.id}
                  className="rounded-md border bg-card/40 p-3 space-y-2"
                >
                  <div className="flex items-start gap-2">
                    <FileText className="size-4 mt-0.5 text-muted-foreground shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-medium text-sm truncate">
                          {doc.filename}
                        </span>
                        <StatusBadge status={doc.status} />
                        <span className="text-xs text-muted-foreground">
                          {formatBytes(doc.size)} · {formatDate(doc.created_at)}
                        </span>
                      </div>
                      {doc.status === 'ready' && doc.summary && (
                        <p className="mt-2 text-sm text-foreground/90 whitespace-pre-wrap">
                          {doc.summary}
                        </p>
                      )}
                      {doc.status === 'ready' && !doc.summary && (
                        <p className="mt-2 text-xs text-muted-foreground italic">
                          (Sin resumen)
                        </p>
                      )}
                      {doc.status === 'processing' && (
                        <p className="mt-2 text-xs text-muted-foreground flex items-center gap-1">
                          <Loader2 className="size-3 animate-spin" />
                          Extrayendo texto, chunking y resumiendo…
                        </p>
                      )}
                      {doc.status === 'error' && (
                        <p className="mt-2 text-xs text-destructive">
                          {doc.error_message ?? 'Error desconocido al procesar el archivo.'}
                        </p>
                      )}
                    </div>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      onClick={() => setToDelete(doc)}
                      disabled={deleteMut.isPending}
                      aria-label={`Eliminar ${doc.filename}`}
                      className="text-muted-foreground hover:text-destructive"
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </section>

      <ConfirmDialog
        open={toDelete !== null}
        title="Eliminar documento"
        description={
          toDelete ? (
            <>
              ¿Eliminar <strong>{toDelete.filename}</strong>? También se
              borrarán los chunks asociados. Esta acción no se puede deshacer.
            </>
          ) : null
        }
        onCancel={() => setToDelete(null)}
        onConfirm={() => deleteMut.mutateAsync(toDelete!.id)}
      />
    </div>
  )
}
