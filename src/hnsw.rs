use rand::distributions::{Distribution, Uniform};
use std::collections::{BinaryHeap, HashMap, HashSet};
use std::cmp::Ordering;
use std::f32;
use std::error::Error;
use std::fmt;


#[derive(Debug)]
pub enum HNSWError {
    DimensionMismatch { expected: usize, got: usize },
    EmptyVector,
    InvalidParameters(String),
}

#[derive(Debug, Clone)]
struct Node {
    vector: Vec<f32>,
    neighbors: Vec<Vec<usize>>,  // Changed to use indices instead of strings
}

#[derive(Debug, Clone, PartialEq)]
struct Candidate {
    idx: usize,
    distance: f32,
}

impl Eq for Candidate {}

impl PartialOrd for Candidate {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        other.distance.partial_cmp(&self.distance)
    }
}

impl Ord for Candidate {
    fn cmp(&self, other: &Self) -> Ordering {
        self.partial_cmp(other).unwrap_or(Ordering::Equal)
    }
}

pub struct HNSWIndex {
    nodes: Vec<Node>,  // Changed to Vec for stable indexing
    entry_point: Option<usize>,
    max_layers: usize,
    ef_construction: usize,
    m: usize,
    m0: usize,
    level_multiplier: f32,
    dimensions: Option<usize>,
}

impl HNSWIndex {
    pub fn new(max_layers: usize, ef_construction: usize, m: usize) -> Result<Self, HNSWError> {
        if max_layers == 0 || ef_construction == 0 || m < 2 {
            return Err(HNSWError::InvalidParameters("Invalid parameters".into()));
        }

        Ok(Self {
            nodes: Vec::new(),
            entry_point: None,
            max_layers,
            ef_construction,
            m,
            m0: m * 2,
            level_multiplier: 1.0 / (m as f32).ln(),
            dimensions: None,
        })
    }

    fn validate_vector(&self, vector: &[f32]) -> Result<(), HNSWError> {
        if vector.is_empty() {
            return Err(HNSWError::EmptyVector);
        }

        if let Some(dim) = self.dimensions {
            if vector.len() != dim {
                return Err(HNSWError::DimensionMismatch {
                    expected: dim,
                    got: vector.len(),
                });
            }
        }

        Ok(())
    }

    fn distance(&self, a: &[f32], b: &[f32]) -> f32 {
        a.iter()
            .zip(b.iter())
            .map(|(x, y)| (x - y) * (x - y))
            .sum::<f32>()
            .sqrt()
    }

    fn generate_random_level(&self) -> usize {
        let mut rng = rand::thread_rng();
        let uniform = Uniform::new(0.0f32, 1.0);
        ((-uniform.sample(&mut rng).ln() * self.level_multiplier) as usize)
            .clamp(0, self.max_layers - 1)
    }

    fn search_layer(
        &self,
        entry_point: usize,
        query: &[f32],
        ef: usize,
        level: usize,
        visited: &mut HashSet<usize>,
    ) -> Vec<Candidate> {
        let mut candidates = BinaryHeap::new();
        let mut results = BinaryHeap::new();
        
        let dist = self.distance(&self.nodes[entry_point].vector, query);
        candidates.push(Candidate { idx: entry_point, distance: dist });
        results.push(Candidate { idx: entry_point, distance: dist });
        visited.insert(entry_point);

        // Keep searching while candidates exist
        while let Some(current) = candidates.pop() {
            // Only break if we have enough results AND current distance is worse than our worst result
            if results.len() >= ef && results.peek().map_or(false, |worst| current.distance > worst.distance) {
                break;
            }

            let node = &self.nodes[current.idx];
            if level >= node.neighbors.len() || node.neighbors[level].is_empty() {
                continue;
            }

            for &neighbor_idx in &node.neighbors[level] {
                if visited.insert(neighbor_idx) {
                    let dist = self.distance(&self.nodes[neighbor_idx].vector, query);
                    
                    // More permissive condition for adding candidates
                    candidates.push(Candidate { idx: neighbor_idx, distance: dist });
                    
                    // Add to results if either:
                    // 1. We haven't found enough results yet
                    // 2. This is better than our worst result
                    if results.len() < ef || dist < results.peek().unwrap().distance {
                        results.push(Candidate { idx: neighbor_idx, distance: dist });
                        
                        // Only trim results when we exceed ef
                        while results.len() > ef {
                            results.pop();
                        }
                    }
                }
            }
        }

        results.into_sorted_vec()
    }

    fn select_neighbors(
        &self,
        candidates: Vec<Candidate>,
        m: usize,
        query: &[f32],
    ) -> Vec<usize> {
        if candidates.len() <= m {
            return candidates.into_iter().map(|c| c.idx).collect();
        }

        let mut selected = Vec::with_capacity(m);
        let mut remaining: HashSet<_> = candidates.iter().map(|c| c.idx).collect();

        while selected.len() < m && !remaining.is_empty() {
            let mut best_dist = f32::MAX;
            let mut best_idx = None;

            for &idx in &remaining {
                let dist = self.distance(&self.nodes[idx].vector, query);
                if dist < best_dist {
                    best_dist = dist;
                    best_idx = Some(idx);
                }
            }

            if let Some(idx) = best_idx {
                selected.push(idx);
                remaining.remove(&idx);
            }
        }

        selected
    }

    pub fn insert(&mut self, id: String, vector: Vec<f32>) -> Result<(), HNSWError> {
        self.validate_vector(&vector)?;

        if self.dimensions.is_none() {
            self.dimensions = Some(vector.len());
        }

        let level = self.generate_random_level();

        let node = Node {
            vector: vector.clone(),
            neighbors: vec![vec![]; level + 1],
        };
        self.nodes.push(node);
        let new_idx = self.nodes.len() - 1;

        if self.entry_point.is_none() {
            self.entry_point = Some(new_idx);
            return Ok(());
        }

        let mut entry_point = self.entry_point.unwrap();
        let mut curr_dist = self.distance(&self.nodes[entry_point].vector, &vector);
        
        let max_level = self.nodes[entry_point].neighbors.len().saturating_sub(1);
        let mut visited = HashSet::new();

        for l in (level..=max_level).rev() {
            let mut changed = true;
            while changed {
                changed = false;
                
                let neighbors = &self.nodes[entry_point].neighbors[l];
                for &neighbor_idx in neighbors {
                    let dist = self.distance(&self.nodes[neighbor_idx].vector, &vector);
                    if dist < curr_dist {
                        curr_dist = dist;
                        entry_point = neighbor_idx;
                        changed = true;
                    }
                }
            }
        }

        for l in (0..=level).rev() {
            visited.clear();
            let candidates = self.search_layer(entry_point, &vector, self.ef_construction, l, &mut visited);
            let selected = self.select_neighbors(candidates, if l == 0 { self.m0 } else { self.m }, &vector);

            self.nodes[new_idx].neighbors[l] = selected.clone();

            for &neighbor_idx in &selected {
                let neighbor = &mut self.nodes[neighbor_idx];
                while neighbor.neighbors.len() <= l {
                    neighbor.neighbors.push(vec![]);
                }
                neighbor.neighbors[l].push(new_idx);
            }

            entry_point = new_idx;
        }

        if level > self.nodes[self.entry_point.unwrap()].neighbors.len() - 1 {
            self.entry_point = Some(new_idx);
        }

        Ok(())
    }

    pub fn search(&self, query: &[f32], k: usize) -> Result<Vec<(String, f32)>, HNSWError> {
        self.validate_vector(query)?;

        if k == 0 {
            return Err(HNSWError::InvalidParameters("k must be greater than 0".into()));
        }

        if let Some(entry_point) = self.entry_point {
            let mut visited = HashSet::new();
            let results = self.search_layer(entry_point, query, k, 0, &mut visited);
            
            Ok(results
                .into_iter()
                .map(|c| (c.idx.to_string(), c.distance))
                .collect())
        } else {
            Ok(vec![])
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_basic_functionality() {
        let mut index = HNSWIndex::new(4, 100, 16).unwrap();
        
        // Insert some test vectors
        index.insert("0".into(), vec![0.0, 0.0, 0.0]).unwrap();
        index.insert("1".into(), vec![1.0, 0.0, 0.0]).unwrap();
        index.insert("2".into(), vec![0.0, 1.0, 0.0]).unwrap();
        
        // Search for nearest neighbors
        let query = vec![0.5, 0.5, 0.0];
        let results = index.search(&query, 2).unwrap();
        
        assert_eq!(results.len(), 2);
    }

    #[test]
    fn test_dimension_validation() {
        let mut index = HNSWIndex::new(4, 100, 16).unwrap();
        
        index.insert("0".into(), vec![0.0, 0.0]).unwrap();
        assert!(matches!(
            index.insert("1".into(), vec![0.0]),
            Err(HNSWError::DimensionMismatch { .. })
        ));
    }
}