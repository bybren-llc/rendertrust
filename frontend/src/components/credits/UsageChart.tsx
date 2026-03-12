/**
 * Simple bar chart showing daily credit usage over the last 7 days.
 * Pure CSS/Tailwind implementation -- no chart library dependency.
 *
 * MIT License
 * Copyright (c) 2026 ByBren, LLC
 */

import { type DailyUsage } from '../../hooks/useCredits'

function shortDay(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { weekday: 'short' })
}

function shortDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
  })
}

interface UsageChartProps {
  data: DailyUsage[]
  loading: boolean
}

export default function UsageChart({ data, loading }: UsageChartProps) {
  if (loading) {
    return (
      <div className="flex h-48 items-center justify-center text-sm text-gray-400">
        Loading usage data...
      </div>
    )
  }

  if (data.length === 0) {
    return (
      <div className="flex h-48 items-center justify-center text-sm text-gray-400">
        No usage data available.
      </div>
    )
  }

  const max = Math.max(...data.map((d) => d.credits), 1)

  return (
    <div className="space-y-2">
      <div className="flex items-end gap-2" style={{ height: 160 }}>
        {data.map((day) => {
          const pct = (day.credits / max) * 100
          return (
            <div
              key={day.date}
              className="group relative flex flex-1 flex-col items-center justify-end"
              style={{ height: '100%' }}
            >
              <div className="pointer-events-none absolute -top-8 z-10 hidden rounded bg-gray-800 px-2 py-1 text-xs text-white shadow group-hover:block dark:bg-gray-200 dark:text-gray-800">
                {day.credits.toLocaleString()} credits
              </div>
              <div
                className="w-full rounded-t bg-indigo-500 transition-all hover:bg-indigo-400 dark:bg-indigo-400 dark:hover:bg-indigo-300"
                style={{
                  height: `${Math.max(pct, 2)}%`,
                  minHeight: day.credits > 0 ? 4 : 0,
                }}
              />
            </div>
          )
        })}
      </div>
      <div className="flex gap-2">
        {data.map((day) => (
          <div
            key={day.date}
            className="flex-1 text-center text-xs text-gray-500 dark:text-gray-400"
          >
            <div>{shortDay(day.date)}</div>
            <div>{shortDate(day.date)}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
