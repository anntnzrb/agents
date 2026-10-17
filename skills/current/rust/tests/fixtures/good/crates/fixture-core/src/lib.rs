//! Checked arithmetic with tests that distinguish its boundary behavior.
#![forbid(unsafe_code)]

/// Advances a counter without wrapping at its maximum value.
///
/// ```
/// assert_eq!(fixture_core::advance(10), Some(11));
/// ```
#[must_use = "Handle a saturated counter explicitly"]
pub const fn advance(value: u8) -> Option<u8> {
    value.checked_add(1)
}

/// Reports whether a requested allocation fits within its available capacity.
#[must_use = "Check capacity before allocating"]
pub const fn fits_capacity(requested: usize, available: usize) -> bool {
    requested <= available
}

/// Maps one command-line argument to a process exit status.
///
/// Returns 0 for a counter that can advance, 1 for a saturated or invalid
/// counter, and 2 when the argument is missing.
#[must_use = "Return the status to the process"]
pub fn exit_status(argument: Option<&str>) -> u8 {
    match argument.map(str::parse::<u8>) {
        None => 2,
        Some(Ok(value)) if advance(value).is_some() => 0,
        Some(Ok(_) | Err(_)) => 1,
    }
}

#[cfg(test)]
mod tests {
    use super::{advance, exit_status, fits_capacity};

    #[test]
    fn maps_arguments_to_exit_status() {
        assert_eq!(exit_status(None), 2, "a missing argument is a usage error");
        assert_eq!(exit_status(Some("10")), 0, "an advancing counter succeeds");
        assert_eq!(exit_status(Some("255")), 1, "a saturated counter fails");
        assert_eq!(exit_status(Some("ten")), 1, "an invalid counter fails");
    }

    #[test]
    fn enforces_capacity_boundary() {
        assert!(fits_capacity(0, 0), "an empty allocation needs no capacity");
        assert!(fits_capacity(2, 3), "a smaller request must fit");
        assert!(fits_capacity(3, 3), "an exact fit must be accepted");
        assert!(
            !fits_capacity(4, 3),
            "an oversized request must be rejected"
        );
    }

    #[test]
    fn advances_and_rejects_overflow() {
        for value in 0..u8::MAX {
            assert_eq!(
                advance(value),
                Some(value.saturating_add(1)),
                "advance must preserve the checked successor"
            );
        }
        assert_eq!(advance(u8::MAX), None, "overflow must be rejected");
    }
}
