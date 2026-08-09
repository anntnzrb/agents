# Modern Go Features

Key language and runtime features by Go version. Load the appropriate version-scoped file for details.

| Version | Key Features | Read |
|---|---|---|
| 1.22 | Loop variable semantics, range-over-int, ServeMux routing, rand/v2 | `modern-1.22-1.23.md` |
| 1.23 | Stable iter.Seq/Seq2, stdlib iterator integration | `modern-1.22-1.23.md` |
| 1.24 | Swiss Tables maps, generic type aliases, go.mod tool directive, B.Loop | `modern-1.24-1.26.md` |
| 1.25 | testing/synctest, container-aware GOMAXPROCS | `modern-1.24-1.26.md` |
| 1.26 | new(expr), errors.AsType, Green Tea GC, go fix modernizers | `modern-1.24-1.26.md` |

## Minimum version recommendation

- New applications: `go 1.26` in `go.mod`
- Libraries: pin `go` to the oldest version supporting your API; use `toolchain go1.26.3` for builds
- Avoid GOEXPERIMENT-only features as default practice
