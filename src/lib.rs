//! AlphaDB is a high-performance vector similarity search engine
//!
//! # Quick Start
//! ```rust
//! use alphadb::builder::VectorIndexBuilder;
//! use alphadb::SimilarityType;
//!
//! let mut index = VectorIndexBuilder::new(128)
//!     .with_similarity(SimilarityType::Cosine)
//!     .build();
//!
//! let query_vec = vec![0.1; 128];
//! let results = index.query(&query_vec, 10);
//! ```

use std::collections::HashMap;
use thiserror::Error;
use tracing::{debug, info};

#[derive(Error, Debug)]
pub enum IndexError {
    #[error("Dimension mismatch: expected {expected}, got {got}")]
    DimensionMismatch { expected: usize, got: usize },
    #[error("Invalid parameter: {0}")]
    InvalidParameter(String),
}

#[derive(Clone, Copy)]
pub enum SimilarityType {
    Cosine,
    Euclidean,
    DotProduct,
}

pub struct IndexParams {
    pub dimension: usize,
    pub m: usize,
    pub ef_construction: usize,
    pub ef_search: usize,
    pub similarity_type: SimilarityType,
}

impl Default for IndexParams {
    fn default() -> Self {
        Self {
            dimension: 384,
            m: 16,
            ef_construction: 200,
            ef_search: 50,
            similarity_type: SimilarityType::Cosine,
        }
    }
}

pub struct VectorIndex {
    params: IndexParams,
    vectors: HashMap<String, Vec<f32>>,
}

impl VectorIndex {
    pub fn new(params: IndexParams) -> Self {
        info!(
            "Initializing VectorIndex with dimension {}",
            params.dimension
        );
        Self {
            params,
            vectors: HashMap::new(),
        }
    }

    pub fn insert(&mut self, id: &str, vector: &[f32]) -> Result<(), IndexError> {
        debug!("Inserting vector with id: {}", id);

        if vector.len() != self.params.dimension {
            return Err(IndexError::DimensionMismatch {
                expected: self.params.dimension,
                got: vector.len(),
            });
        }

        self.vectors.insert(id.to_string(), vector.to_vec());
        info!("Successfully inserted vector {}", id);
        Ok(())
    }

    pub fn query(&self, query_vec: &[f32], k: usize) -> Result<Vec<(String, f32)>, IndexError> {
        debug!("Querying for {} nearest neighbors", k);

        if query_vec.len() != self.params.dimension {
            return Err(IndexError::DimensionMismatch {
                expected: self.params.dimension,
                got: query_vec.len(),
            });
        }

        let mut distances: Vec<(String, f32)> = self
            .vectors
            .iter()
            .map(|(id, v)| {
                let sim = match self.params.similarity_type {
                    SimilarityType::Cosine => cosine_similarity(query_vec, v),
                    SimilarityType::Euclidean => -euclidean_distance(query_vec, v),
                    SimilarityType::DotProduct => dot_product(query_vec, v),
                };
                (id.clone(), sim)
            })
            .collect();

        distances.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap());
        distances.truncate(k);
        Ok(distances)
    }
}

fn cosine_similarity(u: &[f32], v: &[f32]) -> f32 {
    let dot = dot_product(u, v);
    let norm_u = u.iter().map(|x| x * x).sum::<f32>().sqrt();
    let norm_v = v.iter().map(|x| x * x).sum::<f32>().sqrt();
    if norm_u == 0.0 || norm_v == 0.0 {
        return 0.0;
    }
    dot / (norm_u * norm_v)
}

fn euclidean_distance(u: &[f32], v: &[f32]) -> f32 {
    u.iter()
        .zip(v)
        .map(|(x, y)| (x - y) * (x - y))
        .sum::<f32>()
        .sqrt()
}

fn dot_product(u: &[f32], v: &[f32]) -> f32 {
    u.iter().zip(v).map(|(x, y)| x * y).sum()
}

pub mod builder;

#[cfg(feature = "rest")]
pub mod rest;

#[cfg(feature = "python")]
pub mod python;

mod hnsw;

pub use crate::hnsw::HNSWIndex;
