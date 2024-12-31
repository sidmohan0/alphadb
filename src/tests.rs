#[cfg(test)]
mod tests {
    use super::*;
    use rand::Rng;

    fn create_random_vector(dim: usize) -> Vec<f32> {
        let mut rng = rand::thread_rng();
        (0..dim).map(|_| rng.gen()).collect()
    }

    #[test]
    fn test_basic_insertion() {
        let mut index = HNSWIndex::new(4, 100, 16);
        let vec1 = vec![1.0, 0.0, 0.0];
        let vec2 = vec![0.0, 1.0, 0.0];
        let vec3 = vec![0.0, 0.0, 1.0];

        index.insert("a".to_string(), vec1);
        index.insert("b".to_string(), vec2);
        index.insert("c".to_string(), vec3);

        assert_eq!(index.nodes.len(), 3);
    }

    #[test]
    fn test_basic_search() {
        let mut index = HNSWIndex::new(4, 100, 16);
        
        // Insert some vectors
        let vectors = vec![
            (vec![1.0, 0.0, 0.0], "a"),
            (vec![0.0, 1.0, 0.0], "b"),
            (vec![0.0, 0.0, 1.0], "c"),
            (vec![0.5, 0.5, 0.0], "d"),
        ];

        for (vec, id) in vectors {
            index.insert(id.to_string(), vec);
        }

        // Search for nearest to [1,0,0]
        let results = index.search(&[1.0, 0.0, 0.0], 2);
        assert_eq!(results[0].0, "a");  // Closest should be "a"
    }

    #[test]
    fn test_large_scale() {
        let mut index = HNSWIndex::new(4, 100, 16);
        let dim = 128;
        let n_vectors = 1000;

        // Insert random vectors
        for i in 0..n_vectors {
            let vec = create_random_vector(dim);
            index.insert(i.to_string(), vec);
        }

        // Test search
        let query = create_random_vector(dim);
        let results = index.search(&query, 10);
        
        assert_eq!(results.len(), 10);
        
        // Verify distances are sorted
        for i in 1..results.len() {
            assert!(results[i-1].1 <= results[i].1);
        }
    }
} 