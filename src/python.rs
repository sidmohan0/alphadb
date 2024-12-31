use crate::IndexParams;
use crate::VectorIndex;
use pyo3::prelude::*;

#[pymodule]
fn alphadb(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<PyVectorIndex>()?;
    Ok(())
}

#[pyclass]
struct PyVectorIndex {
    inner: VectorIndex,
}

#[pymethods]
impl PyVectorIndex {
    #[new]
    fn new() -> Self {
        Self {
            inner: VectorIndex::new(IndexParams::default()),
        }
    }
}
