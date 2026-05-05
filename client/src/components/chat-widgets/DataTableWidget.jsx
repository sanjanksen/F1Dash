function alignmentClass(align) {
  if (align === 'right') return 'text-right'
  if (align === 'center') return 'text-center'
  return 'text-left'
}

function cellClass(align) {
  return [
    'px-3 py-3 align-top text-[14px] leading-6 text-foreground',
    align === 'right' ? 'text-right font-mono-data tabular-nums' : '',
    align === 'center' ? 'text-center' : '',
  ].filter(Boolean).join(' ')
}

export default function DataTableWidget({ widget }) {
  const columns = Array.isArray(widget?.columns) ? widget.columns : []
  const rows = Array.isArray(widget?.rows) ? widget.rows : []

  if (!columns.length || !rows.length) return null

  return (
    <section className="max-w-3xl overflow-hidden border-y border-border/80 py-1">
      <div className="flex flex-col gap-1 px-1 py-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h3 className="text-[15px] font-semibold text-foreground">{widget.title || 'Table'}</h3>
          {widget.subtitle ? (
            <p className="mt-1 text-sm leading-6 text-muted-foreground">{widget.subtitle}</p>
          ) : null}
        </div>
        <div className="text-xs text-muted-foreground">{rows.length} rows</div>
      </div>

      <div className="app-scrollbar overflow-x-auto">
        <table className="w-full min-w-[36rem] border-collapse">
          <thead>
            <tr className="border-y border-border/70">
              {columns.map((column) => (
                <th
                  key={column.key}
                  className={`px-3 py-2 text-xs font-medium text-muted-foreground ${alignmentClass(column.align)}`}
                  scope="col"
                >
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, rowIndex) => (
              <tr key={rowIndex} className="border-b border-border/55 last:border-b-0">
                {columns.map((column) => (
                  <td key={column.key} className={cellClass(column.align)}>
                    {row?.[column.key] ?? ''}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {widget.note ? (
        <p className="px-1 py-3 text-sm leading-6 text-muted-foreground">{widget.note}</p>
      ) : null}
    </section>
  )
}
