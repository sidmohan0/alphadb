FROM node:20-bookworm-slim AS deps
WORKDIR /app

COPY package.json package-lock.json ./
COPY apps/api/package.json apps/api/package.json
COPY apps/web/package.json apps/web/package.json
COPY apps/tui/package.json apps/tui/package.json
COPY packages/market-core/package.json packages/market-core/package.json
COPY packages/sdk/package.json packages/sdk/package.json

RUN npm ci

RUN node -e "const { execFileSync } = require('node:child_process'); const version = require('./node_modules/rollup/package.json').version; const libc = process.report?.getReport?.().header?.glibcVersionRuntime ? 'gnu' : 'musl'; const pkg = '@rollup/rollup-' + process.platform + '-' + process.arch + '-' + libc; execFileSync('npm', ['install', '--no-save', pkg + '@' + version], { stdio: 'inherit' });"

FROM deps AS build
WORKDIR /app

COPY . .

RUN npm run build --workspace @alphadb/sdk \
  && npm run build --workspace @alphadb/web

FROM node:20-bookworm-slim AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV PORT=8080

COPY --from=build /app/apps/web/dist ./dist
COPY --from=build /app/apps/web/server.mjs ./server.mjs

EXPOSE 8080

CMD ["node", "server.mjs"]
