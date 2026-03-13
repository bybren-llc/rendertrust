// Copyright (c) 2025 Words To Film By, Inc.
// Licensed under the MIT License. See LICENSE-MIT for details.

import type { LeaderboardEntry, NetworkStats } from "./types";

/**
 * Mock leaderboard data for the community portal MVP.
 * Will be replaced with real API data once the backend endpoint is available.
 */
export const MOCK_LEADERBOARD: LeaderboardEntry[] = [
  {
    rank: 1,
    nodeId: "node-a7f3",
    nodeName: "AlphaRender-01",
    jobsCompleted: 12847,
    uptimePercent: 99.97,
    totalEarnings: 45230.5,
  },
  {
    rank: 2,
    nodeId: "node-b2e9",
    nodeName: "CloudForge-EU",
    jobsCompleted: 11293,
    uptimePercent: 99.92,
    totalEarnings: 39870.25,
  },
  {
    rank: 3,
    nodeId: "node-c8d1",
    nodeName: "PixelStorm-US",
    jobsCompleted: 10584,
    uptimePercent: 99.88,
    totalEarnings: 37150.0,
  },
  {
    rank: 4,
    nodeId: "node-d4f6",
    nodeName: "RenderHive-AP",
    jobsCompleted: 9876,
    uptimePercent: 99.85,
    totalEarnings: 34620.75,
  },
  {
    rank: 5,
    nodeId: "node-e1a3",
    nodeName: "TrustNode-DE",
    jobsCompleted: 8932,
    uptimePercent: 99.79,
    totalEarnings: 31340.0,
  },
  {
    rank: 6,
    nodeId: "node-f7b8",
    nodeName: "NexusGPU-UK",
    jobsCompleted: 8201,
    uptimePercent: 99.74,
    totalEarnings: 28780.5,
  },
  {
    rank: 7,
    nodeId: "node-g3c5",
    nodeName: "QuantumEdge-JP",
    jobsCompleted: 7645,
    uptimePercent: 99.68,
    totalEarnings: 26830.25,
  },
  {
    rank: 8,
    nodeId: "node-h9d2",
    nodeName: "BlazeFarm-CA",
    jobsCompleted: 7012,
    uptimePercent: 99.61,
    totalEarnings: 24590.0,
  },
  {
    rank: 9,
    nodeId: "node-i5e7",
    nodeName: "VortexNode-AU",
    jobsCompleted: 6389,
    uptimePercent: 99.55,
    totalEarnings: 22410.75,
  },
  {
    rank: 10,
    nodeId: "node-j2f4",
    nodeName: "StellarRender-SG",
    jobsCompleted: 5847,
    uptimePercent: 99.48,
    totalEarnings: 20510.5,
  },
  {
    rank: 11,
    nodeId: "node-k6g1",
    nodeName: "IronClad-BR",
    jobsCompleted: 5234,
    uptimePercent: 99.42,
    totalEarnings: 18360.0,
  },
  {
    rank: 12,
    nodeId: "node-l8h9",
    nodeName: "ThunderGPU-IN",
    jobsCompleted: 4891,
    uptimePercent: 99.35,
    totalEarnings: 17150.25,
  },
  {
    rank: 13,
    nodeId: "node-m0i3",
    nodeName: "PrimeNode-FR",
    jobsCompleted: 4523,
    uptimePercent: 99.29,
    totalEarnings: 15870.5,
  },
  {
    rank: 14,
    nodeId: "node-n4j7",
    nodeName: "ArcticFarm-NO",
    jobsCompleted: 4102,
    uptimePercent: 99.21,
    totalEarnings: 14390.0,
  },
  {
    rank: 15,
    nodeId: "node-o1k5",
    nodeName: "SolarEdge-ZA",
    jobsCompleted: 3789,
    uptimePercent: 99.14,
    totalEarnings: 13290.75,
  },
];

/**
 * Mock network statistics for the stats overview cards.
 */
export const MOCK_STATS: NetworkStats = {
  totalNodes: 247,
  totalJobs: 156432,
  networkUptime: 99.73,
  totalPayouts: 548920.5,
};
