FROM node:20-alpine AS deps
WORKDIR /app

COPY package.json package-lock.json ./
COPY apps/api/package.json apps/api/package.json
COPY apps/web/package.json apps/web/package.json
COPY apps/tui/package.json apps/tui/package.json
COPY packages/market-core/package.json packages/market-core/package.json
COPY packages/sdk/package.json packages/sdk/package.json

RUN npm ci

FROM node:20-alpine AS prod-deps
WORKDIR /app

COPY package.json package-lock.json ./
COPY apps/api/package.json apps/api/package.json
COPY apps/web/package.json apps/web/package.json
COPY apps/tui/package.json apps/tui/package.json
COPY packages/market-core/package.json packages/market-core/package.json
COPY packages/sdk/package.json packages/sdk/package.json

RUN npm ci --omit=dev

FROM deps AS build
WORKDIR /app

COPY . .

RUN npm run build --workspace @alphadb/sdk \
  && npm run build --workspace @alphadb/api

FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV PORT=4000

COPY --from=prod-deps /app/node_modules ./node_modules
COPY --from=build /app/package.json ./package.json
COPY --from=build /app/package-lock.json ./package-lock.json
COPY --from=build /app/apps/api/package.json ./apps/api/package.json
COPY --from=build /app/apps/api/dist ./apps/api/dist
COPY --from=build /app/apps/api/src/markets/infra/db/userStateSchema.sql ./apps/api/src/markets/infra/db/userStateSchema.sql
COPY --from=build /app/apps/api/src/polymarket/infra/db/schemas.sql ./apps/api/src/polymarket/infra/db/schemas.sql
COPY --from=build /app/packages/market-core ./packages/market-core
COPY --from=build /app/packages/sdk ./packages/sdk
COPY --from=build /app/deploy ./deploy

EXPOSE 4000

CMD ["node", "apps/api/dist/index.js"]
