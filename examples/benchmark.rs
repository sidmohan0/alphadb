use alphadb::HNSWIndex;
use rand::Rng;
use std::time::Instant;

fn create_random_vector(dim: usize) -> Vec<f32> {
    let mut rng = rand::thread_rng();
    let mut vec: Vec<f32> = (0..dim).map(|_| rng.gen_range(-1.0..1.0)).collect();
    let norm: f32 = vec.iter().map(|x| x * x).sum::<f32>().sqrt();
    for x in &mut vec {
        *x /= norm.max(1e-10);
    }
    vec
}

fn benchmark_insertion(n_vectors: usize, dim: usize) -> (HNSWIndex, Vec<Vec<f32>>, f64) {
    let mut index = HNSWIndex::new(16, 128, 16).unwrap();
    let mut vectors = Vec::with_capacity(n_vectors);
    
    println!("Starting insertions...");
    let start = Instant::now();
    
    for i in 0..n_vectors {
        let vec = create_random_vector(dim);
        vectors.push(vec.clone());
        
        if i % 1000 == 0 {
            println!("  Inserted {} vectors", i);
        }
        
        if let Err(e) = index.insert(i.to_string(), vec) {
            eprintln!("Error inserting vector {}: {:?}", i, e);
            continue;
        }
    }
    
    let duration = start.elapsed().as_secs_f64();
    println!("Insertion complete!");
    println!("  Vectors: {}", n_vectors);
    println!("  Dimensions: {}", dim);
    println!("  Total time: {:.2}s", duration);
    println!("  Vectors/second: {:.2}", n_vectors as f64 / duration);
    
    (index, vectors, duration)
}

fn benchmark_search(index: &HNSWIndex, queries: &[Vec<f32>], k: usize) -> f64 {
    let mut successful_queries = 0;
    let start = Instant::now();
    
    println!("\nStarting search benchmark...");
    for (i, query) in queries.iter().enumerate() {
        if i % 10 == 0 {
            println!("  Running query {}/{}", i, queries.len());
        }
        
        match index.search(query, k) {
            Ok(results) => {
                successful_queries += 1;
                if i == 0 {
                    println!("\nSample search result:");
                    for (id, dist) in results.iter().take(3) {
                        println!("  ID: {}, Distance: {:.4}", id, dist);
                    }
                }
            }
            Err(e) => {
                eprintln!("Search error for query {}: {:?}", i, e);
                eprintln!("Query vector: {:?}", &query[..5]);
            }
        }
    }
    
    let duration = start.elapsed().as_secs_f64();
    println!("\nSearch benchmark complete!");
    println!("  Successful queries: {}/{}", successful_queries, queries.len());
    println!("  k: {}", k);
    println!("  Total time: {:.2}s", duration);
    println!("  Queries/second: {:.2}", queries.len() as f64 / duration);
    
    duration
}

fn benchmark_accuracy(index: &HNSWIndex, vectors: &[Vec<f32>], n_queries: usize) {
    let mut rng = rand::thread_rng();
    let mut successful = 0;
    
    println!("\nAccuracy Benchmark:");
    for _ in 0..n_queries {
        let idx = rng.gen_range(0..vectors.len());
        let query = &vectors[idx];
        
        match index.search(query, 1) {
            Ok(results) => {
                if !results.is_empty() && results[0].0 == idx.to_string() {
                    successful += 1;
                }
            }
            Err(e) => eprintln!("Search error: {:?}", e),
        }
    }
    
    println!("  Accuracy: {:.2}%", (successful as f64 / n_queries as f64) * 100.0);
}

fn main() {
    let n_vectors = 1_000;
    let n_queries = 10;
    let dim = 8;
    let k = 4;
    let m = 16;
    let max_layers = 16;

    println!("Starting benchmark with:");
    println!("  Vectors: {}", n_vectors);
    println!("  Dimensions: {}", dim);
    println!("  Queries: {}", n_queries);
    println!("  k: {}", k);
    println!();

    let (index, vectors, _) = benchmark_insertion(n_vectors, dim);
    
    println!("\nGenerating queries...");
    let queries: Vec<Vec<f32>> = (0..n_queries)
        .map(|_| create_random_vector(dim))
        .collect();
    
    benchmark_search(&index, &queries, k);
    
    println!("\nRunning accuracy test...");
    benchmark_accuracy(&index, &vectors, 5);
    
    let memory_mb = (n_vectors * (
        dim * 4 + // vector storage
        64 + // overhead
        (m * 8 * max_layers) // neighbor connections
    )) as f64 / 1024.0 / 1024.0;
    println!("\nMemory Usage (estimated): {:.2} MB", memory_mb);
} 
