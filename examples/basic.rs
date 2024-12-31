use alphadb::{builder::VectorIndexBuilder, SimilarityType};
use tracing_subscriber;

fn main() {
    // Initialize logging
    tracing_subscriber::fmt::init();

    // Create index using builder
    let mut index = VectorIndexBuilder::new(384)
        .with_similarity(SimilarityType::Cosine)
        .with_ef_construction(100)
        .build();

    // Create some dummy vectors
    let vec1 = vec![0.1_f32; 384];
    let vec2 = vec![0.2_f32; 384];

    // Insert them
    index.insert("doc1", &vec1).unwrap();
    index.insert("doc2", &vec2).unwrap();

    // Query
    let query = vec![0.15_f32; 384];
    let results = index.query(&query, 2).unwrap();

    println!("\nQuery results:");
    for (id, similarity) in results {
        println!("ID: {}, Similarity: {:.6}", id, similarity);
    }
}
