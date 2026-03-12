/**
 * Credit package selector with "Buy Now" buttons.
 *
 * MIT License
 * Copyright (c) 2026 ByBren, LLC
 */

import { useState } from 'react'
import { CREDIT_PACKAGES, type CreditPackage } from '../../hooks/useCredits'

interface CreditPackagesProps {
  onBuy: (sku: string) => Promise<void>
  buying: boolean
}

export default function CreditPackages({ onBuy, buying }: CreditPackagesProps) {
  const [selected, setSelected] = useState<string | null>(null)

  async function handleBuy(pkg: CreditPackage) {
    setSelected(pkg.sku)
    await onBuy(pkg.sku)
    setSelected(null)
  }

  return (
    <div className="grid gap-3 sm:grid-cols-3">
      {CREDIT_PACKAGES.map((pkg) => {
        const isActive = buying && selected === pkg.sku
        const unitPrice = (pkg.price_usd / pkg.credits).toFixed(3)
        return (
          <div
            key={pkg.sku}
            className="flex flex-col items-center rounded-lg border p-4 transition-shadow hover:shadow-md dark:border-gray-700"
          >
            <p className="text-2xl font-bold text-gray-900 dark:text-gray-100">
              {pkg.label}
            </p>
            <p className="mt-1 text-lg font-semibold text-indigo-600 dark:text-indigo-400">
              ${pkg.price_usd}
            </p>
            <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
              ${unitPrice} / credit
            </p>
            <button
              onClick={() => handleBuy(pkg)}
              disabled={buying}
              className="mt-3 w-full rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-indigo-700 disabled:opacity-50 dark:bg-indigo-500 dark:hover:bg-indigo-600"
            >
              {isActive ? 'Opening checkout...' : 'Buy Now'}
            </button>
          </div>
        )
      })}
    </div>
  )
}
