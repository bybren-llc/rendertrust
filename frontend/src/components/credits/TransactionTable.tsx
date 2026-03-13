/**
 * Transaction history table with type badges and "load more" pagination.
 *
 * MIT License
 * Copyright (c) 2026 ByBren, LLC
 */

import { type Transaction, type TransactionType } from '../../hooks/useCredits'

// ---------------------------------------------------------------------------
// Badge helpers
// ---------------------------------------------------------------------------

const TYPE_STYLES: Record<TransactionType, string> = {
  purchase:
    'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400',
  deduction: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400',
  refund: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400',
}

function TypeBadge({ type }: { type: TransactionType }) {
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium capitalize ${TYPE_STYLES[type] ?? ''}`}
    >
      {type}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Format helpers
// ---------------------------------------------------------------------------

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatAmount(amount: number, type: TransactionType): string {
  const sign = type === 'deduction' ? '-' : '+'
  return `${sign}${Math.abs(amount).toLocaleString()}`
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface TransactionTableProps {
  transactions: Transaction[]
  loading: boolean
  hasMore: boolean
  total: number
  onLoadMore: () => void
}

export default function TransactionTable({
  transactions,
  loading,
  hasMore,
  total,
  onLoadMore,
}: TransactionTableProps) {
  if (!loading && transactions.length === 0) {
    return (
      <div className="rounded-lg border border-dashed p-8 text-center text-gray-500 dark:text-gray-400">
        No transactions yet.
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {/* Desktop table */}
      <div className="hidden overflow-x-auto rounded-lg border md:block">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 dark:bg-gray-800">
            <tr>
              <th className="px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-300">
                Date
              </th>
              <th className="px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-300">
                Type
              </th>
              <th className="px-4 py-3 text-right font-medium text-gray-600 dark:text-gray-300">
                Amount
              </th>
              <th className="px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-300">
                Description
              </th>
              <th className="px-4 py-3 text-right font-medium text-gray-600 dark:text-gray-300">
                Balance After
              </th>
            </tr>
          </thead>
          <tbody className="divide-y dark:divide-gray-700">
            {transactions.map((tx) => (
              <tr
                key={tx.id}
                className="hover:bg-gray-50 dark:hover:bg-gray-800/50"
              >
                <td className="whitespace-nowrap px-4 py-3">
                  {formatDate(tx.date)}
                </td>
                <td className="px-4 py-3">
                  <TypeBadge type={tx.type} />
                </td>
                <td
                  className={`whitespace-nowrap px-4 py-3 text-right font-mono ${
                    tx.type === 'deduction'
                      ? 'text-red-600 dark:text-red-400'
                      : 'text-green-600 dark:text-green-400'
                  }`}
                >
                  {formatAmount(tx.amount, tx.type)}
                </td>
                <td className="px-4 py-3 text-gray-600 dark:text-gray-400">
                  {tx.description}
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-right font-mono">
                  {tx.balance_after.toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile cards */}
      <div className="space-y-2 md:hidden">
        {transactions.map((tx) => (
          <div
            key={tx.id}
            className="rounded-lg border p-3 dark:border-gray-700"
          >
            <div className="flex items-center justify-between">
              <TypeBadge type={tx.type} />
              <span
                className={`font-mono text-sm font-semibold ${
                  tx.type === 'deduction'
                    ? 'text-red-600 dark:text-red-400'
                    : 'text-green-600 dark:text-green-400'
                }`}
              >
                {formatAmount(tx.amount, tx.type)}
              </span>
            </div>
            <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
              {tx.description}
            </p>
            <div className="mt-1 flex items-center justify-between text-xs text-gray-500">
              <span>{formatDate(tx.date)}</span>
              <span>Bal: {tx.balance_after.toLocaleString()}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between pt-2">
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Showing {transactions.length} of {total} transactions
        </p>
        {hasMore && (
          <button
            onClick={onLoadMore}
            disabled={loading}
            className="rounded-md border px-4 py-2 text-sm font-medium transition-colors hover:bg-gray-50 disabled:opacity-50 dark:border-gray-600 dark:hover:bg-gray-800"
          >
            {loading ? 'Loading...' : 'Load More'}
          </button>
        )}
      </div>
    </div>
  )
}
