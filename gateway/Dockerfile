# ---------- build stage ----------
FROM rust:1.82 as builder
WORKDIR /app

# Cache dependencies first for faster rebuilds
COPY Cargo.toml Cargo.lock ./
RUN cargo fetch

# Copy source code and build
COPY src ./src
RUN cargo build --release

# ---------- runtime stage ----------
FROM debian:bookworm-slim

# Install runtime dependencies
RUN apt-get update && \
    apt-get install -y libpq5 ca-certificates curl && \
    rm -rf /var/lib/apt/lists/*

# Copy the built binary
COPY --from=builder /app/target/release/ws_recorder /usr/local/bin/ws_recorder

# Set up non-root user for security
RUN useradd --create-home --shell /bin/bash recorder
USER recorder

# Default config path (can be overridden via environment)
ENV CONFIG=/config/config.toml

# Expose metrics port
EXPOSE 9187

# Health check endpoint
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -sf http://localhost:9187/metrics || exit 1

ENTRYPOINT ["/usr/local/bin/ws_recorder"]
CMD ["--config", "/config/config.toml"]