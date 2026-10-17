//! Wildcard match violation.
/// A closed set whose variants must be matched explicitly.
#[derive(Debug, Clone, Copy)]
pub enum Mode {
    /// First mode.
    First,
    /// Second mode.
    Second,
    /// Third mode.
    Third,
}

/// Hides future modes behind a wildcard.
#[must_use = "Read the result"]
pub const fn number(mode: Mode) -> u8 {
    match mode {
        Mode::First => 1,
        _ => 2,
    }
}
