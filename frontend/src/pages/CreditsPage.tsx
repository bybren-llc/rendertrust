/**
 * Credit Dashboard -- balance display, usage chart, buy-credits flow,
 * and paginated transaction history.
 *
 * MIT License
 * Copyright (c) 2026 ByBren, LLC
 */

import { useEffect } from 'react'
import {
  useBalance,
  useTransactionHistory,
  useUsageChart,
  useBuyCredits,
} from '../hooks/useCredits'
import TransactionTable from '../components/credits/TransactionTable'
import UsageChart from '../components/credits/UsageChart'
import CreditPackages from '../components/credits/CreditPackages'

export default function CreditsPage() {
  const {
    balance,
    loading: balLoading,
    error: balError,
    refresh: refreshBalance,
  } = useBalance()

  const {
    transactions,
    loading: txLoading,
    error: txError,
    hasMore,
    total,
    loadMore,
    refresh: refreshTx,
  } = useTransactionHistory()

  const {
    usage,
    loading: usageLoading,
    error: usageError,
  } = useUsageChart(7)

  const { buy, loading: buyLoading, error: buyError } = useBuyCredits()

  // Listen for success callback from Stripe redirect
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    if (params.get('checkout') === 'success') {
      refreshBalance()
      refreshTx()
      const url = new URL(window.location.href)
      url.searchParams.delete('checkout')
      url.searchParams.delete('session_id')
      window.history.replaceState({}, '', url.toString())
    }
  }, [refreshBalance, refreshTx])

  return (
    <div className="mx-auto max-w-5xl space-y-8 p-4 sm:p-6">
      {/* Page header */}
      <div>
        <h1 className="text-3xl font-bold text-gray-900 dark:text-gray-100">
          Credits
        </h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          Manage your credit balance, view usage, and purchase more credits.
        </p>
      </div>

      {/* Top row: balance + usage chart */}
      <div className="grid gap-6 md:grid-cols-3">
        {/* Balance card */}
        <div className="flex flex-col items-center justify-center rounded-xl border bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
          <p className="text-sm font-medium uppercase tracking-wide text-gray-500 dark:text-gray-400">
            Available Balance
          </p>
          {balLoading ? (
            <div className="mt-2 h-10 w-32 animate-pulse rounded bg-gray-200 dark:bg-gray-700" />
          ) : balError ? (
            <p className="mt-2 text-sm text-red-600 dark:text-red-400">
              {balError}
            </p>
          ) : (
            <p className="mt-2 text-5xl font-extrabold tabular-nums text-gray-900 dark:text-white">
              {(balance ?? 0).toLocaleString()}
            </p>
          )}
          <p className="mt-1 text-xs text-gray-400">credits</p>
        </div>

        {/* Usage chart */}
        <div className="rounded-xl border bg-white p-6 shadow-sm md:col-span-2 dark:border-gray-700 dark:bg-gray-900">
          <h2 className="mb-4 text-sm font-medium uppercase tracking-wide text-gray-500 dark:text-gray-400">
            Usage (Last 7 Days)
          </h2>
          {usageError ? (
            <p className="text-sm text-red-600 dark:text-red-400">
              {usageError}
            </p>
          ) : (
            <UsageChart data={usage} loading={usageLoading} />
          )}
        </div>
      </div>

      {/* Buy credits section */}
      <div className="rounded-xl border bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
        <h2 className="mb-4 text-lg font-semibold text-gray-900 dark:text-gray-100">
          Buy Credits
        </h2>
        {buyError && (
          <p className="mb-3 text-sm text-red-600 dark:text-red-400">
            {buyError}
          </p>
        )}
        <CreditPackages onBuy={buy} buying={buyLoading} />
      </div>

      {/* Transaction history */}
      <div className="rounded-xl border bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
        <h2 className="mb-4 text-lg font-semibold text-gray-900 dark:text-gray-100">
          Transaction History
        </h2>
        {txError && (
          <p className="mb-3 text-sm text-red-600 dark:text-red-400">
            {txError}
          </p>
        )}
        <TransactionTable
          transactions={transactions}
          loading={txLoading}
          hasMore={hasMore}
          total={total}
          onLoadMore={loadMore}
        />
      </div>
    </div>
  )
}
