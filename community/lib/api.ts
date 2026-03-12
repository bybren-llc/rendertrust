// Copyright (c) 2025 Words To Film By, Inc.
// Licensed under the MIT License. See LICENSE-MIT for details.

import type { LeaderboardResponse } from "./types";
import { MOCK_LEADERBOARD, MOCK_STATS } from "./mock-data";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * Fetches the community leaderboard data from the RenderTrust API.
 * Falls back to mock data if the API is unavailable.
 */
export async function fetchLeaderboard(): Promise<LeaderboardResponse> {
  try {
    const response = await fetch(
      `${API_URL}/api/v1/community/leaderboard`,
      {
        next: { revalidate: 60 },
        signal: AbortSignal.timeout(5000),
      }
    );

    if (!response.ok) {
      throw new Error(`API returned ${response.status}`);
    }

    const data: LeaderboardResponse = await response.json();
    return data;
  } catch {
    // Fall back to mock data when the API is unavailable.
    // This allows the portal to function during development
    // or when the backend endpoint is not yet deployed.
    console.warn(
      "Community API unavailable, using mock data. " +
        "Set NEXT_PUBLIC_API_URL to point to a running backend."
    );

    return {
      leaderboard: MOCK_LEADERBOARD,
      stats: MOCK_STATS,
      updatedAt: new Date().toISOString(),
    };
  }
}
