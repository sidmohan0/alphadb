use crate::VectorIndex;
use axum::{extract::State, http::StatusCode, routing::post, Json, Router};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tokio::sync::RwLock;
use tracing::{debug, error, info};

#[derive(Deserialize, Debug)]
pub struct InsertRequest {
    id: String,
    vector: Vec<f32>,
}

#[derive(Deserialize, Debug)]
pub struct QueryRequest {
    vector: Vec<f32>,
    k: Option<usize>, // Optional, will default to 10
}

#[derive(Serialize)]
pub struct QueryResponse {
    matches: Vec<Match>,
}

#[derive(Serialize)]
pub struct Match {
    id: String,
    score: f32,
}

#[derive(Serialize)]
pub struct ErrorResponse {
    error: String,
    details: Option<String>,
}

pub type SharedIndex = Arc<RwLock<VectorIndex>>;

pub async fn insert_handler(
    State(index): State<SharedIndex>,
    Json(req): Json<InsertRequest>,
) -> Result<Json<&'static str>, (StatusCode, Json<ErrorResponse>)> {
    info!(
        "Received insert request for id: {} with vector length {}",
        req.id,
        req.vector.len()
    );

    let mut index = index.write().await;
    match index.insert(&req.id, &req.vector) {
        Ok(_) => {
            info!("Successfully inserted vector with id: {}", req.id);
            Ok(Json("OK"))
        }
        Err(e) => {
            error!("Failed to insert vector: {}", e);
            Err((
                StatusCode::BAD_REQUEST,
                Json(ErrorResponse {
                    error: format!(
                        "Insert failed: Vector dimension mismatch. Expected 384, got {}",
                        req.vector.len()
                    ),
                    details: Some(e.to_string()),
                }),
            ))
        }
    }
}

pub async fn query_handler(
    State(index): State<SharedIndex>,
    Json(req): Json<QueryRequest>,
) -> Result<Json<QueryResponse>, (StatusCode, Json<ErrorResponse>)> {
    info!(
        "Received query request with vector length: {}",
        req.vector.len()
    );

    let k = req.k.unwrap_or(10);
    let index = index.read().await;

    match index.query(&req.vector, k) {
        Ok(results) => {
            info!("Query successful, found {} matches", results.len());
            Ok(Json(QueryResponse {
                matches: results
                    .into_iter()
                    .map(|(id, score)| Match { id, score })
                    .collect(),
            }))
        }
        Err(e) => {
            error!("Query failed: {}", e);
            Err((
                StatusCode::BAD_REQUEST,
                Json(ErrorResponse {
                    error: format!(
                        "Query failed: Vector dimension mismatch. Expected 384, got {}",
                        req.vector.len()
                    ),
                    details: Some(e.to_string()),
                }),
            ))
        }
    }
}

pub fn create_router(index: SharedIndex) -> Router {
    info!("Creating REST API router");
    Router::new()
        .route("/insert", post(insert_handler))
        .route("/query", post(query_handler))
        .with_state(index)
}
