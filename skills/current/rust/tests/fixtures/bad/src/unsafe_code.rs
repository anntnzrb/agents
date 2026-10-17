//! Undocumented unsafe violation.
/// Reads through a raw pointer without documenting safety.
#[must_use = "Read the result"]
pub fn undocumented(value: &u32) -> u32 {
    let pointer = std::ptr::from_ref(value);
    unsafe { pointer.read() }
}
