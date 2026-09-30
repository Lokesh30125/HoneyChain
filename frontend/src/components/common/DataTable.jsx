import { EmptyState } from '@/components/common/EmptyState';
import { ErrorState } from '@/components/common/ErrorState';
import { SkeletonBlock } from '@/components/common/LoadingState';
import { Button } from '@/components/ui/Button';

/**
 * Generic table with built-in loading, empty, error and pagination states.
 *
 * Column contract:
 *   { key, header, render?(row), align?, className? }
 *
 * Every list screen in later phases (hives, batches, tests, chain events,
 * alerts) renders through this component, so table behaviour stays consistent.
 */
export function DataTable({
  columns = [],
  rows = [],
  rowKey = (row) => row.id,
  loading = false,
  error = null,
  onRetry = null,
  emptyTitle = 'No records found',
  emptyDescription,
  emptyAction = null,
  caption,
  meta = null,
  onPageChange = null,
  onRowClick = null,
  skeletonRows = 4,
  className = '',
}) {
  if (error && !loading) {
    return <ErrorState error={error} onRetry={onRetry} className={className} />;
  }

  const hasRows = rows.length > 0;
  const totalPages = meta?.total_pages ?? null;
  const page = meta?.page ?? 1;
  const showPagination = Boolean(meta && totalPages && totalPages > 1 && onPageChange);

  return (
    <div className={className}>
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-sand-200 text-sm">
          {caption ? <caption className="sr-only">{caption}</caption> : null}
          <thead className="bg-sand-100/70">
            <tr>
              {columns.map((column) => (
                <th
                  key={column.key}
                  scope="col"
                  className={[
                    'whitespace-nowrap px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-ink-soft',
                    column.align === 'right' ? 'text-right' : '',
                    column.align === 'center' ? 'text-center' : '',
                    column.className || '',
                  ]
                    .filter(Boolean)
                    .join(' ')}
                >
                  {column.header}
                </th>
              ))}
            </tr>
          </thead>

          <tbody className="divide-y divide-sand-200 bg-white">
            {loading
              ? Array.from({ length: skeletonRows }).map((_, rowIndex) => (
                  <tr key={`skeleton-${rowIndex}`}>
                    {columns.map((column) => (
                      <td key={column.key} className="px-4 py-3.5">
                        <SkeletonBlock className="h-4 w-full max-w-[12rem]" />
                      </td>
                    ))}
                  </tr>
                ))
              : rows.map((row) => (
                  <tr
                    key={rowKey(row)}
                    onClick={onRowClick ? () => onRowClick(row) : undefined}
                    className={
                      onRowClick
                        ? 'cursor-pointer transition-colors hover:bg-honey-50/50'
                        : 'transition-colors hover:bg-sand-50'
                    }
                  >
                    {columns.map((column) => (
                      <td
                        key={column.key}
                        className={[
                          'px-4 py-3.5 align-middle text-ink-soft',
                          column.align === 'right' ? 'text-right' : '',
                          column.align === 'center' ? 'text-center' : '',
                          column.cellClassName || '',
                        ]
                          .filter(Boolean)
                          .join(' ')}
                      >
                        {column.render ? column.render(row) : (row[column.key] ?? '—')}
                      </td>
                    ))}
                  </tr>
                ))}
          </tbody>
        </table>
      </div>

      {!loading && !hasRows ? (
        <EmptyState title={emptyTitle} description={emptyDescription} action={emptyAction} />
      ) : null}

      {showPagination ? (
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-sand-200 px-4 py-3">
          <p className="text-xs text-ink-muted">
            Page {page} of {totalPages} · {meta.total_items} record
            {meta.total_items === 1 ? '' : 's'}
          </p>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              size="sm"
              disabled={page <= 1}
              onClick={() => onPageChange(page - 1)}
            >
              Previous
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={page >= totalPages}
              onClick={() => onPageChange(page + 1)}
            >
              Next
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export default DataTable;
