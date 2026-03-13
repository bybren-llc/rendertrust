# RenderTrust Creator

Electron desktop application for RenderTrust creators to submit jobs, monitor status, and manage credits.

## Tech Stack

- **Framework**: Electron 28 + React 18
- **Build Tool**: Vite 5
- **Language**: TypeScript 5
- **Styling**: Tailwind CSS 3.4
- **Routing**: React Router DOM 6

## Prerequisites

- Node.js 18+ (LTS recommended)
- npm 9+ or yarn 1.22+

## Setup

```bash
cd frontend/
npm install
```

## Development

Start the Vite dev server and Electron together:

```bash
npm run dev
```

This runs Vite on `http://localhost:5173` and opens the Electron window pointed at it.

## Build

Build for production:

```bash
npm run build
```

This runs `vite build` to compile the renderer, then `electron-builder` to package the app.

## Type Checking

```bash
npm run type-check
```

## Linting

```bash
npm run lint
```

## Project Structure

```
frontend/
├── electron/           # Electron main process
│   ├── main.ts         # Window creation, app lifecycle
│   └── preload.ts      # Preload script (IPC bridge)
├── src/                # React renderer
│   ├── components/     # Shared UI components
│   │   └── Layout.tsx  # Navigation shell (sidebar + header)
│   ├── pages/          # Route page components
│   │   ├── DashboardPage.tsx
│   │   ├── JobsPage.tsx
│   │   ├── CreditsPage.tsx
│   │   └── SettingsPage.tsx
│   ├── styles/
│   │   └── globals.css # Tailwind imports
│   ├── App.tsx         # Router configuration
│   └── main.tsx        # React entry point
├── index.html          # HTML entry point
├── package.json        # Dependencies and scripts
├── vite.config.ts      # Vite configuration
├── tailwind.config.js  # Tailwind configuration
├── postcss.config.js   # PostCSS configuration
├── tsconfig.json       # TypeScript config (renderer)
└── tsconfig.node.json  # TypeScript config (Vite/Node)
```

## Security

The Electron main process is configured with security best practices:

- `nodeIntegration: false` -- renderer cannot access Node.js APIs directly
- `contextIsolation: true` -- preload scripts run in isolated context
- Content Security Policy set in `index.html`
- Use `electron/preload.ts` with `contextBridge` to expose specific APIs

## License

MIT -- see [LICENSE-MIT](../LICENSE-MIT)
