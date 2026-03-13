# RenderTrust Community Portal

Public-facing community leaderboard showing top node operators and network statistics.

## Setup

### Prerequisites

- Node.js 18+ (20 LTS recommended)
- npm 9+

### Install

```bash
cd community
npm install
```

### Environment

Copy the environment template and configure:

```bash
cp .env.example .env.local
```

| Variable | Description | Default |
| --- | --- | --- |
| `NEXT_PUBLIC_API_URL` | RenderTrust API base URL | `http://localhost:8000` |
| `NEXT_PUBLIC_REFRESH_INTERVAL` | Leaderboard auto-refresh interval (seconds) | `60` |

### Development

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

### Build

```bash
npm run build
npm start
```

### Type Check

```bash
npm run type-check
```

### Lint

```bash
npm run lint
```

## Architecture

This is a standalone Next.js 14 application using App Router.

```
community/
  app/
    globals.css       # Tailwind CSS base styles
    layout.tsx        # Root layout with metadata
    page.tsx          # Main leaderboard page (server component, ISR)
  components/
    hero.tsx          # Hero section with branding and CTAs
    network-stats.tsx # Network stats overview grid
    stat-card.tsx     # Animated counter stat card
    leaderboard-table.tsx  # Sortable leaderboard with auto-refresh
    footer.tsx        # Footer with links
  lib/
    api.ts            # API client with mock data fallback
    mock-data.ts      # Mock leaderboard and stats data
    types.ts          # TypeScript type definitions
```

### Data Flow

1. On initial page load, the server fetches leaderboard data via `fetchLeaderboard()`
2. If the API (`/api/v1/community/leaderboard`) is unavailable, mock data is used
3. The page hydrates on the client for interactive sorting and auto-refresh
4. Auto-refresh fetches new data every 60 seconds (configurable)
5. ISR revalidates server-rendered content every 60 seconds

### API Integration

The portal expects a `GET /api/v1/community/leaderboard` endpoint returning:

```json
{
  "leaderboard": [
    {
      "rank": 1,
      "nodeId": "node-a7f3",
      "nodeName": "AlphaRender-01",
      "jobsCompleted": 12847,
      "uptimePercent": 99.97,
      "totalEarnings": 45230.50
    }
  ],
  "stats": {
    "totalNodes": 247,
    "totalJobs": 156432,
    "networkUptime": 99.73,
    "totalPayouts": 548920.50
  },
  "updatedAt": "2026-03-12T10:30:00.000Z"
}
```

Until the backend endpoint is implemented, the portal uses built-in mock data.

## License

MIT - See [LICENSE-MIT](../LICENSE-MIT) for details.
