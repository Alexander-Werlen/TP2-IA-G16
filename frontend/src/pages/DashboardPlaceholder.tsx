import { useAuthStore } from '@/store/auth'

export default function DashboardPlaceholder() {
  const user = useAuthStore((s) => s.user)

  return (
    <div className="flex-1 flex items-center justify-center p-6">
      <div className="max-w-md w-full text-center space-y-4">
        <div className="mx-auto size-14 rounded-full bg-accent flex items-center justify-center text-2xl">
          💬
        </div>
        <div className="space-y-1">
          <h1 className="text-xl font-semibold">
            Hola, {user?.name ?? 'estudiante'}
          </h1>
          <p className="text-sm text-muted-foreground">
            Elegí un chat del panel de la izquierda para empezar, o creá un
            módulo y un chat nuevos.
          </p>
        </div>
        <ul className="text-xs text-muted-foreground text-left space-y-1.5 border rounded-md p-3 bg-card/40">
          <li>
            <span className="font-medium text-foreground">+ Módulo</span> en una
            materia para agrupar chats por tema.
          </li>
          <li>
            <span className="font-medium text-foreground">+ Chat</span> dentro
            de un módulo para abrir una conversación nueva.
          </li>
          <li>
            <span className="font-medium text-foreground">📄 Documentos</span> en
            un módulo para subir material (PDF/DOCX/TXT).
          </li>
        </ul>
      </div>
    </div>
  )
}
