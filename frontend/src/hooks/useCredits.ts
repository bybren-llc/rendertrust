/**
 * Credit hooks for balance, transaction history, and Stripe checkout.
 *
 * MIT License
 * Copyright (c) 2026 ByBren, LLC
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import { api } from '../lib/api'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface CreditBalance {
  balance: number
  updated_at: string
}

export type TransactionType = 'purchase' | 'deduction' | 'refund'

export interface Transaction {
  id: string
  date: string
  type: TransactionType
  amount: number
  description: string
  balance_after: number
}

export interface TransactionPage {
  items: Transaction[]
  total: number
  page: number
  per_page: number
  has_more: boolean
}

export interface DailyUsage {
  date: string
  credits: number
}

export interface CreditPackage {
  sku: string
  credits: number
  price_usd: number
  label: string
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const CREDIT_PACKAGES: CreditPackage[] = [
  { sku: 'cred10', credits: 100, price_usd: 10, label: '100 credits' },
  { sku: 'cred50', credits: 500, price_usd: 40, label: '500 credits' },
  { sku: 'cred100', credits: 1000, price_usd: 70, label: '1,000 credits' },
]

// ---------------------------------------------------------------------------
// useBalance
// ---------------------------------------------------------------------------

export function useBalance() {
  const [balance, setBalance] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchBalance = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.get<CreditBalance>('/api/v1/credits/balance')
      setBalance(data.balance)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load balance')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchBalance()
  }, [fetchBalance])

  return { balance, loading, error, refresh: fetchBalance }
}

// ---------------------------------------------------------------------------
// useTransactionHistory
// ---------------------------------------------------------------------------

export function useTransactionHistory(perPage = 10) {
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const loadingRef = useRef(false)

  const fetchPage = useCallback(
    async (pageNum: number, append = false) => {
      if (loadingRef.current) return
      loadingRef.current = true
      setLoading(true)
      setError(null)
      try {
        const data = await api.get<TransactionPage>(
          `/api/v1/credits/history?page=${pageNum}&per_page=${perPage}`,
        )
        setTransactions((prev) =>
          append ? [...prev, ...data.items] : data.items,
        )
        setTotal(data.total)
        setHasMore(data.has_more)
        setPage(pageNum)
      } catch (err) {
        setError(
          err instanceof Error ? err.message : 'Failed to load transactions',
        )
      } finally {
        setLoading(false)
        loadingRef.current = false
      }
    },
    [perPage],
  )

  useEffect(() => {
    fetchPage(1)
  }, [fetchPage])

  const loadMore = useCallback(() => {
    if (hasMore && !loadingRef.current) {
      fetchPage(page + 1, true)
    }
  }, [fetchPage, hasMore, page])

  const refresh = useCallback(() => {
    setTransactions([])
    fetchPage(1)
  }, [fetchPage])

  return { transactions, loading, error, hasMore, total, loadMore, refresh }
}

// ---------------------------------------------------------------------------
// useUsageChart
// ---------------------------------------------------------------------------

export function useUsageChart(days = 7) {
  const [usage, setUsage] = useState<DailyUsage[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const data = await api.get<DailyUsage[]>(`/api/v1/credits/usage?days=${days}`)
        if (!cancelled) setUsage(data)
      } catch (err) {
        if (!cancelled)
          setError(
            err instanceof Error ? err.message : 'Failed to load usage data',
          )
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [days])

  return { usage, loading, error }
}

// ---------------------------------------------------------------------------
// useBuyCredits
// ---------------------------------------------------------------------------

export function useBuyCredits() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const buy = useCallback(async (sku: string) => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.post<{ url: string }>('/api/v1/credits/checkout', { sku })
      // In Electron, open in external browser; in web, redirect
      if (
        typeof window !== 'undefined' &&
        (window as Record<string, unknown>).electronAPI
      ) {
        const electronApi = (window as Record<string, unknown>).electronAPI as {
          openExternal: (url: string) => void
        }
        electronApi.openExternal(data.url)
      } else {
        window.location.href = data.url
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start checkout')
    } finally {
      setLoading(false)
    }
  }, [])

  return { buy, loading, error }
}
