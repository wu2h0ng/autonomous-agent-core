# Dockerfile — AI Native Business Data Agent OS (Frontend)
# Next.js 16 workspace frontend for the Trusted Loop UI.
#
# Build context: apps/workspace/frontend/
#
# Usage:
#   docker build -t agent-os-frontend -f apps/workspace/frontend/Dockerfile apps/workspace/frontend/

FROM node:20-alpine AS base

# ── Stage 1: Install dependencies ────────────────────────────────────────────
FROM base AS deps

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

# ── Stage 2: Build the Next.js application ───────────────────────────────────
FROM base AS builder

WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

# NEXT_PUBLIC_ variables are baked at build time in Next.js.
# Override at build time if needed: --build-arg NEXT_PUBLIC_API_URL=...
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ARG NEXT_PUBLIC_RUN_KEY=development-key
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_PUBLIC_RUN_KEY=$NEXT_PUBLIC_RUN_KEY

# Disable Next.js telemetry during build
ENV NEXT_TELEMETRY_DISABLED=1

RUN npm run build

# ── Stage 3: Production runtime ──────────────────────────────────────────────
FROM base AS runner

WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1

# Run as non-root for security
RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# Copy built assets
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

ENV PORT=3000 \
    HOSTNAME="0.0.0.0"

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://127.0.0.1:3000/ || exit 1

CMD ["node", "server.js"]
