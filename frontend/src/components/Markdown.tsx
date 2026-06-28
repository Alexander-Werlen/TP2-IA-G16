import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { ComponentPropsWithoutRef } from 'react'

const CITATION_RE = /\s*\[doc:[^\]]+\]/g

export function stripCitations(s: string): string {
  return s.replace(CITATION_RE, '')
}

type Props = {
  content: string
}

export function Markdown({ content }: Props) {
  return (
    <div className="markdown-body break-words">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => <p className="my-1 leading-relaxed">{children}</p>,
          ul: ({ children }) => <ul className="my-1 ml-5 list-disc">{children}</ul>,
          ol: ({ children }) => <ol className="my-1 ml-5 list-decimal">{children}</ol>,
          li: ({ children }) => <li className="my-0.5">{children}</li>,
          strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
          em: ({ children }) => <em className="italic">{children}</em>,
          a: ({ children, href }) => (
            <a
              href={href}
              target="_blank"
              rel="noreferrer noopener"
              className="text-primary underline underline-offset-2"
            >
              {children}
            </a>
          ),
          code: ({ inline, className, children }: ComponentPropsWithoutRef<'code'> & { inline?: boolean }) => {
            if (inline) {
              return (
                <code className="rounded bg-muted px-1 py-0.5 font-mono text-[12px]">
                  {children}
                </code>
              )
            }
            return (
              <code className={className}>{children}</code>
            )
          },
          pre: ({ children }) => (
            <pre className="my-1 overflow-x-auto rounded bg-muted p-2 text-[12px]">
              {children}
            </pre>
          ),
          h1: ({ children }) => <h1 className="mt-2 mb-1 text-base font-semibold">{children}</h1>,
          h2: ({ children }) => <h2 className="mt-2 mb-1 text-[15px] font-semibold">{children}</h2>,
          h3: ({ children }) => <h3 className="mt-2 mb-1 text-sm font-semibold">{children}</h3>,
          blockquote: ({ children }) => (
            <blockquote className="my-1 border-l-2 border-muted-foreground/40 pl-2 italic text-muted-foreground">
              {children}
            </blockquote>
          ),
          hr: () => <hr className="my-2 border-muted-foreground/20" />,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}
