use alphadb::{builder::VectorIndexBuilder, rest::create_router, SimilarityType};
use std::sync::Arc;
use tokio::sync::RwLock;
use tracing::{info, Level};
use tracing_subscriber::{self, fmt::format::FmtSpan};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Initialize logging with more detailed configuration
    tracing_subscriber::fmt()
        .with_max_level(Level::DEBUG)
        .with_target(true)
        .with_thread_ids(true)
        .with_span_events(FmtSpan::CLOSE)
        .init();

    info!("Starting AlphaDB server...");

    // Create the index
    let index = VectorIndexBuilder::new(384)
        .with_similarity(SimilarityType::Cosine)
        .build();

    info!("Vector index initialized with dimension 384");

    // Wrap in Arc<RwLock> for shared state
    let shared_index = Arc::new(RwLock::new(index));

    // Create the router
    let app = create_router(shared_index);

    // Start the server
    let addr = "0.0.0.0:3000";
    info!("Starting server on http://{}", addr);

    let listener = tokio::net::TcpListener::bind(addr).await?;
    info!("Server listening on http://{}", addr);

    axum::serve(listener, app.into_make_service()).await?;

    Ok(())
}
