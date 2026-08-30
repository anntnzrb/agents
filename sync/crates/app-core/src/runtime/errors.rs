use std::fmt;
use std::io;
use thiserror::Error;

/// Runtime errors encountered during filesystem or locking operations.
#[derive(Debug, Error)]
pub enum RuntimeError {
    #[error("io error: {0}")]
    Io(#[from] io::Error),

    #[error("filesystem error: {0}")]
    Fs(String),

    #[error("lock error: {0}")]
    Lock(String),

    #[error("secret template error: {0}")]
    SecretTemplate(String),
}

/// Logs an error message to standard error with the `sync: ` prefix.
pub fn err(message: impl fmt::Display) {
    eprintln!("sync: {message}");
}

/// Logs a warning message to standard error with the `sync: warning: ` prefix.
pub fn warn(message: impl fmt::Display) {
    eprintln!("sync: warning: {message}");
}

/// Returns true if the given `io::Error` has the specified raw OS errno.
#[must_use]
pub fn is_errno(error: &io::Error, code: i32) -> bool {
    error.raw_os_error() == Some(code)
}

/// Returns true if the given `io::Error` is `ErrorKind::NotFound`.
#[must_use]
pub fn is_not_found(error: &io::Error) -> bool {
    error.kind() == io::ErrorKind::NotFound
}

/// Returns true if the given `io::Error` is `ErrorKind::AlreadyExists`.
#[must_use]
pub fn is_already_exists(error: &io::Error) -> bool {
    error.kind() == io::ErrorKind::AlreadyExists
}

/// Extracts a descriptive panic/error message from an Error instance.
#[must_use]
pub fn panic_message(error: &(dyn std::error::Error + 'static)) -> String {
    error.to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_is_errno_and_kind_helpers() {
        let not_found = io::Error::new(io::ErrorKind::NotFound, "file not found");
        assert!(is_not_found(&not_found));
        assert!(!is_already_exists(&not_found));

        let already_exists = io::Error::new(io::ErrorKind::AlreadyExists, "file exists");
        assert!(is_already_exists(&already_exists));
        assert!(!is_not_found(&already_exists));

        let os_error = io::Error::from_raw_os_error(2); // ENOENT on POSIX
        assert!(is_errno(&os_error, 2));
        assert!(!is_errno(&os_error, 13));
    }

    #[test]
    fn test_panic_message() {
        let err = RuntimeError::Fs("cannot sync file".to_string());
        assert_eq!(panic_message(&err), "filesystem error: cannot sync file");
    }
}
