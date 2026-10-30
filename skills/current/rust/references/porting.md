# Porting

Read when porting, translating, or rewriting code from another language into Rust. Port the observable behavior, not the source's structure. A line-by-line transliteration keeps the original's defects and adds borrow-checker friction. [self-check]

## Pin the behavior first

- MUST read the original code, its tests, and its callers before writing Rust. [self-check]
- MUST list each public operation's inputs, outputs, and failure modes, including result ordering, tie-breaking, empty input, whitespace and case handling, integer limits, and which inputs are errors rather than valid edge cases. [self-check]
- MUST port the original tests before the implementation, one Rust test per original test, named so a reader can map each one back. Without original tests, write characterization tests from the behavior list. [cargo test; self-check]
- MUST preserve original bugs and ambiguous behavior and report each one. Fix them only when the user asks. [self-check]
- MUST drop source-language artifacts: manual memory management, out-parameters, null returns, global mutable state, fixed-size buffers whose limit is not behavior, classes that only group functions, and runtime type checks. [self-check]

## Map constructs

| Source construct | Rust |
| --- | --- |
| `malloc`/`free`, `new`/`delete`, create/destroy pairs | Owned types dropped automatically; `Drop` for other resources; `close(self) -> Result` for fallible teardown |
| `NULL`, `None`, `nil`, `null`, or `undefined` meaning absent | `Option<T>` |
| Error codes, `errno`, exceptions, Go `(value, error)` | `Result<T, E>` with a per-operation error enum: one variant per code or exception class, data attributes as fields |
| Out-parameters | The `Ok` value or the error variant |
| Flag bitmasks | An options struct with named fields and `Default`, or `bitflags`; never a raw integer |
| Strings or `#define` codes used as a closed set | An enum with `FromStr` and `Display` for the text form |
| Dicts, plain objects, or classes used as records | Structs with named fields |
| Duck typing, `isinstance`, interfaces | Enums for closed sets, traits for open ones |
| Python `dict` or JavaScript `Map` iteration order | `Vec`, `IndexMap`, or `BTreeMap` when order is observable; `HashMap` changes output order |
| Unbounded `int`, JavaScript `number` | A sized integer or `f64` chosen from the real input range, with checked arithmetic |
| `strtol`, `int()`, `parseInt` | `str::parse` into the matching integer type, mapped into the error enum |
| `sorted(key=...)` | `sort_by_key` or `sort_by`; both are stable, like Python's |
| `char *` with length, `strcmp`, `strcasecmp` | `&str` or `String`, `==`, `eq_ignore_ascii_case` |
| Pointer and count, index loops | Slices and iterators |
| Goroutines and channels | Threads with `std::sync::mpsc`, or async tasks when the original does concurrent I/O |

- MUST NOT write `unsafe` or raw pointers in a port unless the Rust code calls C through FFI. [unsafe_code; governance-check]

## Keep the port proportionate

- MUST use Rust's standard library (`str::lines`, `str::trim`, `str::parse`, `char` methods) instead of reimplementing the source runtime's `splitlines`, `strip`, `int()`, `repr()`, `isspace`, or `strtol`. [self-check]
- MUST report divergences that appear only on exotic input, such as Unicode digits, non-ASCII whitespace, `\r\n`, or unbounded integers. Write a compatibility shim only when the user says such input occurs. [self-check]
- MUST port only the original public surface plus the standard traits Rust callers expect. Add builders, `Index` implementations, or custom iterator types only when the original's callers need them. [self-check]
- MUST keep the original algorithm unless it causes a real defect, such as quadratic time on realistic input. Report any replacement. [self-check]
- SHOULD compare code size, excluding tests and comments. A port from C or C++ is usually about as long as the original. A port from Python or JavaScript is usually two to three times as long. A much larger port usually reimplements the source runtime, grows the API, or replaces the algorithm. [self-check]
- SHOULD run the original and the port over a few dozen realistic and edge-case inputs when the original is runnable, and report every divergence. [cargo test; self-check]

## Report the port

- MUST report porting notes with the result: an API mapping from each original function or type to its Rust equivalent, the test mapping, deliberate differences with reasons, preserved quirks, and the verification commands run. Write them to a file only when the user asks. [self-check]
