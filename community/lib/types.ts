// Copyright (c) 2025 Words To Film By, Inc.
// Licensed under the MIT License. See LICENSE-MIT for details.

/**
 * Represents a node operator entry on the community leaderboard.
 */
export interface LeaderboardEntry {
  rank: number;
  nodeId: string;
  nodeName: string;
  jobsCompleted: number;
  uptimePercent: number;
  totalEarnings: number;
}

/**
 * Network-wide statistics for the stats overview section.
 */
export interface NetworkStats {
  totalNodes: number;
  totalJobs: number;
  networkUptime: number;
  totalPayouts: number;
}

/**
 * Combined API response for the community leaderboard endpoint.
 */
export interface LeaderboardResponse {
  leaderboard: LeaderboardEntry[];
  stats: NetworkStats;
  updatedAt: string;
}

/**
 * Sort direction for leaderboard columns.
 */
export type SortDirection = "asc" | "desc";

/**
 * Sortable column keys on the leaderboard table.
 */
export type SortKey = keyof Pick<
  LeaderboardEntry,
  "rank" | "jobsCompleted" | "uptimePercent" | "totalEarnings"
>;
