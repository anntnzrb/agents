//! Ignored result violation.
/// Silently discards a filesystem error.
pub fn ignored() {
    let _ = std::fs::remove_file("/nonexistent");
}
