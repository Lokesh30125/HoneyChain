import { Button } from '@/components/ui/Button';

/**
 * Page stepper for card lists.
 *
 * `DataTable` paginates tables itself; this is the same control for lists that
 * are not tables (alert cards, timeline entries), so both read identically.
 */
export function PaginationBar({ meta, onPageChange, className = '' }) {
  const totalPages = meta?.total_pages ?? null;
  const page = meta?.page ?? 1;
  if (!meta || !totalPages || totalPages <= 1 || !onPageChange) return null;

  return (
    <div
      className={`flex flex-wrap items-center justify-between gap-3 border-t border-sand-200 px-1 pt-3 ${className}`}
    >
      <p className="text-xs text-ink-muted">
        Page {page} of {totalPages} · {meta.total_items} record{meta.total_items === 1 ? '' : 's'}
      </p>
      <div className="flex gap-2">
        <Button variant="secondary" size="sm" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>
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
  );
}

export default PaginationBar;
