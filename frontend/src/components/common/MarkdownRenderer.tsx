import React from 'react';
import ReactMarkdown from 'react-markdown';

interface MarkdownRendererProps {
  content: string;
  className?: string;
  style?: React.CSSProperties;
}

/**
 * Pre-processes markdown text to remove artificial escape slashes
 * introduced by LLM serializers (e.g. \*\*bold\*\* -> **bold**).
 */
function cleanEscapedMarkdown(raw: string): string {
  if (!raw) return '';
  return raw
    .replace(/\\(\*|_|#|\[|\]|\(|\)|`)/g, '$1')
    .trim();
}

/**
 * Validates that an href is safe to navigate to (no javascript: or data: URIs).
 */
function isSafeUrl(url?: string): boolean {
  if (!url) return false;
  const clean = url.trim().toLowerCase();
  return clean.startsWith('http://') || clean.startsWith('https://') || clean.startsWith('mailto:') || clean.startsWith('/');
}

export const MarkdownRenderer: React.FC<MarkdownRendererProps> = ({ content, className, style }) => {
  const sanitizedContent = cleanEscapedMarkdown(content);

  return (
    <div
      className={`markdown-content ${className || ''}`}
      style={{
        lineHeight: 1.55,
        color: 'var(--text-primary)',
        fontSize: '13.5px',
        wordBreak: 'break-word',
        ...style,
      }}
    >
      <ReactMarkdown
        components={{
          h1: ({ ...props }) => (
            <h1 style={{ fontSize: '18px', fontWeight: 700, margin: '8px 0 6px', color: 'var(--text-primary)' }} {...props} />
          ),
          h2: ({ ...props }) => (
            <h2 style={{ fontSize: '16px', fontWeight: 600, margin: '8px 0 6px', color: 'var(--text-primary)' }} {...props} />
          ),
          h3: ({ ...props }) => (
            <h3 style={{ fontSize: '14.5px', fontWeight: 600, margin: '6px 0 4px', color: 'var(--text-primary)' }} {...props} />
          ),
          p: ({ ...props }) => (
            <p style={{ margin: '0 0 6px', lineHeight: 1.55 }} {...props} />
          ),
          ul: ({ ...props }) => (
            <ul style={{ margin: '4px 0 8px', paddingLeft: '20px', listStyleType: 'disc' }} {...props} />
          ),
          ol: ({ ...props }) => (
            <ol style={{ margin: '4px 0 8px', paddingLeft: '20px', listStyleType: 'decimal' }} {...props} />
          ),
          li: ({ ...props }) => (
            <li style={{ margin: '2px 0' }} {...props} />
          ),
          strong: ({ ...props }) => (
            <strong style={{ fontWeight: 600, color: 'var(--text-primary)' }} {...props} />
          ),
          em: ({ ...props }) => (
            <em style={{ fontStyle: 'italic' }} {...props} />
          ),
          code: ({ className: codeClass, children, ...props }) => {
            const isInline = !codeClass && typeof children === 'string' && !children.includes('\n');
            if (isInline) {
              return (
                <code
                  style={{
                    backgroundColor: 'var(--bg-surface-subtle)',
                    border: '1px solid var(--border-subtle)',
                    borderRadius: 'var(--radius-xs)',
                    padding: '1px 5px',
                    fontSize: '12px',
                    fontFamily: 'monospace',
                    color: 'var(--brand-primary)',
                  }}
                  {...props}
                >
                  {children}
                </code>
              );
            }
            return (
              <pre
                style={{
                  backgroundColor: 'var(--bg-surface-subtle)',
                  border: '1px solid var(--border-default)',
                  borderRadius: 'var(--radius-sm)',
                  padding: '10px 12px',
                  fontSize: '12px',
                  fontFamily: 'monospace',
                  overflowX: 'auto',
                  margin: '8px 0',
                }}
              >
                <code {...props}>{children}</code>
              </pre>
            );
          },
          a: ({ href, children, ...props }) => {
            if (!isSafeUrl(href)) {
              return <span>{children}</span>;
            }
            return (
              <a
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  color: 'var(--brand-primary)',
                  textDecoration: 'underline',
                  fontWeight: 500,
                }}
                {...props}
              >
                {children}
              </a>
            );
          },
          blockquote: ({ ...props }) => (
            <blockquote
              style={{
                borderLeft: '3px solid var(--border-default)',
                paddingLeft: '12px',
                margin: '6px 0',
                color: 'var(--text-secondary)',
                fontStyle: 'italic',
              }}
              {...props}
            />
          ),
        }}
      >
        {sanitizedContent}
      </ReactMarkdown>
    </div>
  );
};
