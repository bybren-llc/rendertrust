// Copyright (c) 2025 Words To Film By, Inc.
// Licensed under the MIT License. See LICENSE-MIT for details.

"use client";

import { useCallback, useEffect, useState } from "react";
import type {
  LeaderboardEntry,
  LeaderboardResponse,
  SortDirection,
  SortKey,
} from "@/lib/types";
import { fetchLeaderboard } from "@/lib/api";

interface LeaderboardTableProps {
  initialData: LeaderboardEntry[];
  initialUpdatedAt: string;
}

function SortArrow({ direction }: { direction: SortDirection }) {
  return (
    <span className="ml-1 inline-block">
      {direction === "asc" ? (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="inline"
        >
          <path d="m18 15-6-6-6 6" />
        </svg>
      ) : (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="inline"
        >
          <path d="m6 9 6 6 6-6" />
        </svg>
      )}
    </span>
  );
}

function RankBadge({ rank }: { rank: number }) {
  if (rank === 1) {
    return (
      <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-yellow-100 text-yellow-700 font-bold text-sm">
        1
      </span>
    );
  }
  if (rank === 2) {
    return (
      <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-gray-100 text-gray-600 font-bold text-sm">
        2
      </span>
    );
  }
  if (rank === 3) {
    return (
      <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-orange-100 text-orange-700 font-bold text-sm">
        3
      </span>
    );
  }
  return (
    <span className="inline-flex h-7 w-7 items-center justify-center text-gray-500 font-medium text-sm">
      {rank}
    </span>
  );
}

/**
 * Sortable leaderboard table showing top node operators.
 * Supports auto-refresh every 60 seconds and manual refresh.
 */
export function LeaderboardTable({
  initialData,
  initialUpdatedAt,
}: LeaderboardTableProps) {
  const [data, setData] = useState<LeaderboardEntry[]>(initialData);
  const [updatedAt, setUpdatedAt] = useState(initialUpdatedAt);
  const [sortKey, setSortKey] = useState<SortKey>("rank");
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");
  const [isRefreshing, setIsRefreshing] = useState(false);

  const refreshInterval = parseInt(
    process.env.NEXT_PUBLIC_REFRESH_INTERVAL ?? "60",
    10
  );

  const handleRefresh = useCallback(async () => {
    setIsRefreshing(true);
    try {
      const response: LeaderboardResponse = await fetchLeaderboard();
      setData(response.leaderboard);
      setUpdatedAt(response.updatedAt);
    } catch (error) {
      console.error("Failed to refresh leaderboard:", error);
    } finally {
      setIsRefreshing(false);
    }
  }, []);

  // Auto-refresh
  useEffect(() => {
    const interval = setInterval(handleRefresh, refreshInterval * 1000);
    return () => clearInterval(interval);
  }, [handleRefresh, refreshInterval]);

  function handleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDirection((prev) => (prev === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      // Default to descending for numeric values (except rank)
      setSortDirection(key === "rank" ? "asc" : "desc");
    }
  }

  const sortedData = [...data].sort((a, b) => {
    const aVal = a[sortKey];
    const bVal = b[sortKey];
    if (aVal < bVal) return sortDirection === "asc" ? -1 : 1;
    if (aVal > bVal) return sortDirection === "asc" ? 1 : -1;
    return 0;
  });

  const sortableHeader = (label: string, key: SortKey) => (
    <th
      className="cursor-pointer select-none px-4 py-3 text-left text-sm font-semibold text-gray-700 hover:text-brand-600 transition-colors"
      onClick={() => handleSort(key)}
    >
      {label}
      {sortKey === key && <SortArrow direction={sortDirection} />}
    </th>
  );

  return (
    <section className="py-8">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-6">
        <h2 className="text-2xl font-bold text-gray-900">
          Top Node Operators
        </h2>
        <div className="flex items-center gap-3">
          <span className="text-sm text-gray-500">
            Updated{" "}
            {new Date(updatedAt).toLocaleTimeString("en-US", {
              hour: "2-digit",
              minute: "2-digit",
            })}
          </span>
          <button
            onClick={handleRefresh}
            disabled={isRefreshing}
            className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 disabled:opacity-50 transition-colors"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              className={isRefreshing ? "animate-spin" : ""}
            >
              <path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8" />
              <path d="M21 3v5h-5" />
            </svg>
            {isRefreshing ? "Refreshing..." : "Refresh"}
          </button>
        </div>
      </div>

      {/* Desktop table */}
      <div className="hidden sm:block overflow-x-auto rounded-xl border border-gray-200 shadow-sm">
        <table className="w-full">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              {sortableHeader("Rank", "rank")}
              <th className="px-4 py-3 text-left text-sm font-semibold text-gray-700">
                Node
              </th>
              {sortableHeader("Jobs Completed", "jobsCompleted")}
              {sortableHeader("Uptime", "uptimePercent")}
              {sortableHeader("Total Earnings", "totalEarnings")}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {sortedData.map((entry) => (
              <tr
                key={entry.nodeId}
                className="hover:bg-gray-50 transition-colors"
              >
                <td className="px-4 py-3">
                  <RankBadge rank={entry.rank} />
                </td>
                <td className="px-4 py-3">
                  <div>
                    <p className="font-medium text-gray-900">
                      {entry.nodeName}
                    </p>
                    <p className="text-xs text-gray-400 font-mono">
                      {entry.nodeId}
                    </p>
                  </div>
                </td>
                <td className="px-4 py-3 text-gray-700 tabular-nums">
                  {entry.jobsCompleted.toLocaleString("en-US")}
                </td>
                <td className="px-4 py-3">
                  <span
                    className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${
                      entry.uptimePercent >= 99.9
                        ? "bg-green-100 text-green-700"
                        : entry.uptimePercent >= 99.5
                          ? "bg-yellow-100 text-yellow-700"
                          : "bg-red-100 text-red-700"
                    }`}
                  >
                    {entry.uptimePercent.toFixed(2)}%
                  </span>
                </td>
                <td className="px-4 py-3 font-medium text-gray-900 tabular-nums">
                  ${entry.totalEarnings.toLocaleString("en-US", {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2,
                  })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile cards */}
      <div className="sm:hidden space-y-3">
        {sortedData.map((entry) => (
          <div
            key={entry.nodeId}
            className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm"
          >
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <RankBadge rank={entry.rank} />
                <div>
                  <p className="font-medium text-gray-900">{entry.nodeName}</p>
                  <p className="text-xs text-gray-400 font-mono">
                    {entry.nodeId}
                  </p>
                </div>
              </div>
              <span
                className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${
                  entry.uptimePercent >= 99.9
                    ? "bg-green-100 text-green-700"
                    : entry.uptimePercent >= 99.5
                      ? "bg-yellow-100 text-yellow-700"
                      : "bg-red-100 text-red-700"
                }`}
              >
                {entry.uptimePercent.toFixed(2)}%
              </span>
            </div>
            <div className="grid grid-cols-2 gap-2 text-sm">
              <div>
                <span className="text-gray-500">Jobs</span>
                <p className="font-medium text-gray-900 tabular-nums">
                  {entry.jobsCompleted.toLocaleString("en-US")}
                </p>
              </div>
              <div>
                <span className="text-gray-500">Earnings</span>
                <p className="font-medium text-gray-900 tabular-nums">
                  ${entry.totalEarnings.toLocaleString("en-US", {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2,
                  })}
                </p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
