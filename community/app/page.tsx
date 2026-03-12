// Copyright (c) 2025 Words To Film By, Inc.
// Licensed under the MIT License. See LICENSE-MIT for details.

import { Hero } from "@/components/hero";
import { NetworkStatsSection } from "@/components/network-stats";
import { LeaderboardTable } from "@/components/leaderboard-table";
import { Footer } from "@/components/footer";
import { fetchLeaderboard } from "@/lib/api";

/**
 * Community Portal homepage.
 *
 * Server-rendered with ISR (revalidate every 60s).
 * Fetches leaderboard data from the API on the server,
 * then hydrates the client for sorting and auto-refresh.
 */
export const revalidate = 60;

export default async function CommunityPage() {
  const { leaderboard, stats, updatedAt } = await fetchLeaderboard();

  return (
    <div className="flex min-h-screen flex-col">
      <Hero />

      <main className="flex-1">
        <div className="mx-auto max-w-6xl px-4">
          <NetworkStatsSection stats={stats} />
          <LeaderboardTable
            initialData={leaderboard}
            initialUpdatedAt={updatedAt}
          />
        </div>
      </main>

      <Footer />
    </div>
  );
}
