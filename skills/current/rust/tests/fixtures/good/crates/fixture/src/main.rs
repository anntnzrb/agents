//! Thin binary that maps its first argument to an exit status through the fixture core.
#![forbid(unsafe_code)]
use std::process::ExitCode;

fn main() -> ExitCode {
    let argument = std::env::args().nth(1);
    ExitCode::from(fixture_core::exit_status(argument.as_deref()))
}
