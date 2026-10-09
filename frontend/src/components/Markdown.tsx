import { Children, isValidElement, type ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { slug } from './slug'

function textOf(node: ReactNode): string {
  return Children.toArray(node).map((c) => (typeof c === 'string' || typeof c === 'number' ? String(c) : isValidElement<{ children?: ReactNode }>(c) ? textOf(c.props.children) : '')).join('')
}

type Heading = 'h1' | 'h2' | 'h3' | 'h4'
const heading = (Tag: Heading) =>
  function H({ children }: { children?: ReactNode }) {
    return <Tag id={slug(textOf(children))}>{children}</Tag>
  }

/** Markdown with GFM tables and ids on headings (so a citation can scroll to its section). */
export default function Markdown({ children, components }: { children: string; components?: Record<string, unknown> }) {
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{ h1: heading('h1'), h2: heading('h2'), h3: heading('h3'), h4: heading('h4'), ...components }}
      >
        {children}
      </ReactMarkdown>
    </div>
  )
}
