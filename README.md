# TypeScript Full-Stack Boilerplate

This is a minimal full-stack setup with:
- **Backend**: Express + TypeScript (`/server`)
- **Frontend**: React + TypeScript + Vite (`/client`)

## Prerequisites
- Node.js 18+
- npm 9+

## Install

```bash
npm install
```

## Development

Run both apps at once:

```bash
npm run dev
```

- Frontend: http://localhost:5173
- Backend: http://localhost:4000

The Vite dev server proxies `/api/*` requests to the backend.

## Build

```bash
npm run build
```

Build both projects (`server/dist` and `client/dist`).
