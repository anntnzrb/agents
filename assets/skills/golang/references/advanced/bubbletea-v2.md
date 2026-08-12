# Bubbletea v2 — CJK/IME-safe TUI

## Use

Read the section matching the task; search headings before loading unrelated detail.

Use **Bubbletea v2 RC**, not v1. v1's software cursor leaves the terminal cursor at `(0, 0)`, so CJK IME candidate windows anchor at top-left instead of the typing position. v2 exposes the real cursor through `tea.View{Cursor: *tea.Cursor}` and `textarea.Cursor()`; disable the textarea's drawn cursor with `SetVirtualCursor(false)`. Both are required. Reference implementation: [`code-yeongyu/bubbletea-wm`](https://github.com/code-yeongyu/bubbletea-wm).

v2 also provides typed mouse events (`tea.MouseClickMsg`, `MouseMotionMsg`, `MouseReleaseMsg`), `View.AltScreen`/`MouseMode`, and a pluggable rendering pipeline.

## `go.mod`

```go
module github.com/your-org/mytui

go 1.23

require (
    charm.land/bubbletea/v2 v2.0.0-rc.2
    charm.land/bubbles/v2   v2.0.0-rc.1
    charm.land/lipgloss/v2  v2.0.0-beta.3
    github.com/mattn/go-runewidth v0.0.19
)
```

v2 imports use `charm.land/`, not `github.com/charmbracelet/...`; this deliberate break separates v2 from v1 until stable.

## Minimal IME-correct app

```go
package main

import (
    "fmt"
    "log"

    tea "charm.land/bubbletea/v2"
    "charm.land/bubbles/v2/textarea"
)

type model struct {
    width, height int
    ta            textarea.Model
}

func initial() model {
    ta := textarea.New()
    ta.Placeholder = "Type Korean / Japanese / Chinese here..."
    ta.SetWidth(60)
    ta.SetHeight(10)
    ta.SetVirtualCursor(false)  // ← THE LINE. Without this, IME breaks.
    ta.Focus()
    return model{ta: ta}
}

func (m model) Init() tea.Cmd { return textarea.Blink }

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
    switch msg := msg.(type) {
    case tea.WindowSizeMsg:
        m.width, m.height = msg.Width, msg.Height
    case tea.KeyPressMsg:
        if msg.String() == "ctrl+c" {
            return m, tea.Quit
        }
    }
    var cmd tea.Cmd
    m.ta, cmd = m.ta.Update(msg)
    return m, cmd
}

func (m model) View() tea.View {
    var view tea.View
    view.AltScreen = true
    view.SetContent(m.ta.View())

    // ── THE OTHER LINE. Position the REAL cursor for IME. ──
    if cursor := m.ta.Cursor(); cursor != nil {
        view.Cursor = cursor
    }
    return view
}

func main() {
    if _, err := tea.NewProgram(initial(), tea.WithAltScreen()).Run(); err != nil {
        log.Fatal(err)
    }
    fmt.Println("bye")
}
```

## CJK display width

CJK characters occupy two terminal cells. `len(string)` measures bytes; `utf8.RuneCountInString` measures runes, not cells. Use `github.com/mattn/go-runewidth` outside lipgloss; `lipgloss/v2` uses it internally (`lipgloss.Width("\u4e2d\u6587")` returns 4, not 2).

```go
import "github.com/mattn/go-runewidth"

func displayWidth(s string) int {
    return runewidth.StringWidth(s)
}

// Wide character occupies two cells; pad accordingly
for _, r := range s {
    cell := string(r)
    w := runewidth.RuneWidth(r)
    canvas = append(canvas, cell)
    if w == 2 {
        canvas = append(canvas, "")  // placeholder for second cell
    }
}
```

## Mouse

Handle typed events:

```go
case tea.MouseClickMsg:
    // msg.X, msg.Y, msg.Button
    return m.handleClick(msg.X, msg.Y, msg.Button)

case tea.MouseMotionMsg:
    return m.handleHover(msg.X, msg.Y)

case tea.MouseReleaseMsg:
    return m.handleRelease(msg.X, msg.Y)
```

Enable it in the view:

```go
view.MouseMode = tea.MouseModeCellMotion  // or MouseModeAll
```

`CellMotion` reports clicks and motion while a button is pressed, including drag. `MouseModeAll` reports motion always; use it for hover only when needed because it is heavier.

## Bubbles and Lipgloss v2

```go
import (
    "charm.land/bubbles/v2/textarea"
    "charm.land/bubbles/v2/textinput"
    "charm.land/bubbles/v2/spinner"
    "charm.land/bubbles/v2/viewport"
    "charm.land/bubbles/v2/list"
    "charm.land/bubbles/v2/table"
    "charm.land/bubbles/v2/help"
    "charm.land/bubbles/v2/key"
)
```

Every v2 text-input component supports `SetVirtualCursor(false)` where applicable. Assume every user input might contain CJK and use it accordingly.

```go
import "charm.land/lipgloss/v2"

titleStyle := lipgloss.NewStyle().
    Bold(true).
    Foreground(lipgloss.Color("230")).
    Background(lipgloss.Color("62")).
    Padding(0, 1).
    Border(lipgloss.RoundedBorder()).
    BorderForeground(lipgloss.Color("63"))

rendered := titleStyle.Render("\u4e2d\u6587")
```

`lipgloss/v2` width and padding account for CJK display width; v1 did too.

## Model–Update–View

```
+--------------------------------------------+
|  tea.Program runs the event loop           |
|                                            |
|  loop:                                     |
|    msg <- queue                            |
|    model, cmd = model.Update(msg)          |
|    view = model.View()                     |
|    render(view)                            |
|    if cmd != nil: go run(cmd) -> queue     |
+--------------------------------------------+
```

- Model: value type, not pointer; use value receivers and return the new model. Pointer receivers can leak state across draws.
- `Update`: pure; no I/O or inline goroutines. Return I/O as `tea.Cmd`; Bubbletea runs it in a goroutine and feeds its result back as a message.
- `View`: read-only; return `tea.View` without changing state.
- `tea.Cmd`: `func() tea.Msg`; runs once, returns one message, exits. Use `tea.Tick` or a self-resending command for repetition.

```go
// One-shot command
func loadData() tea.Cmd {
    return func() tea.Msg {
        data, err := fetch()
        if err != nil { return errMsg{err} }
        return dataLoadedMsg{data}
    }
}

// Periodic
func tickEvery() tea.Cmd {
    return tea.Tick(time.Second, func(t time.Time) tea.Msg {
        return tickMsg{t}
    })
}
```

### Sub-models

```go
type model struct {
    list    list.Model
    input   textinput.Model
    spinner spinner.Model
}

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
    var cmds []tea.Cmd
    var cmd tea.Cmd

    m.list, cmd = m.list.Update(msg)
    cmds = append(cmds, cmd)

    m.input, cmd = m.input.Update(msg)
    cmds = append(cmds, cmd)

    m.spinner, cmd = m.spinner.Update(msg)
    cmds = append(cmds, cmd)

    return m, tea.Batch(cmds...)
}
```

`tea.Batch` runs commands concurrently; results arrive in completion order. Once the model exceeds 250 LOC, split sub-model state/update/view into:

```
internal/ui/
├── model.go          # root model orchestration
├── list.go           # list sub-model state + update + view
├── input.go          # input sub-model
└── spinner.go        # spinner sub-model
```

## Testing with `teatest`

```go
import "charm.land/bubbletea/v2/teatest"

func TestModel_typing_cjk_keeps_cursor_in_position(t *testing.T) {
    // Given
    m := initial()
    tm := teatest.NewTestModel(t, m, teatest.WithInitialTermSize(80, 24))

    // When — simulate typing two CJK wide characters
    tm.Send(tea.KeyPressMsg{Code: '\u4e2d'})
    tm.Send(tea.KeyPressMsg{Code: '\u6587'})

    // Then
    out := tm.FinalOutput(t)
    require.Contains(t, string(out), "\u4e2d\u6587")
    // Cursor should be at column 4 (two wide chars = 4 cells)
    // ...
}
```

`teatest` drives models with synthetic messages and inspects rendered output. Pair it with `autogold` snapshots for full-view regression tests.

## Antipatterns

| Bad | Why | Good |
|---|---|---|
| `tea.Program` + `tea.WithoutSignals()` | Ctrl-C fails | Default signal handling |
| Pointer Model receivers | Violates value semantics | Value receivers; return new model |
| `time.Sleep` in `Update` | Blocks event loop | `tea.Tick` or async `tea.Cmd` |
| `fmt.Println` debugging | Corrupts rendered output | `tea.Printf` or file logging |
| `len(s)` for CJK width | 2x error | `runewidth.StringWidth(s)` |
| Bubbletea v1 with text input | Korean/Japanese IME breaks | v2 + `SetVirtualCursor(false)` |
| Drawing a `█` cursor in v2 | Conflicts with `view.Cursor` | Let terminal handle it |

## Performance

- Gate redraws with a dirty flag when state changes more often than rendered output.
- Use `viewport.Model` for scrollable content; avoid rerendering thousands of lines per keystroke.
- Use `tea.Batch` to parallelize commands; otherwise synchronous commands serialize.
- Use `tea.WithFPS(N)` to cap repaint rate during development.

## When not to use Bubbletea

- One prompt plus one answer: use Charm's `huh`.
- Long-running daemon with occasional status: use `slog` to stderr; use `tea.Program` only if interactivity becomes necessary.
- Non-TTY subprocess such as CI or redirected stdin: `tea.Program` requires a TTY for input. Detect with `term.IsTerminal(int(os.Stdin.Fd()))` and use a non-interactive fallback.

## Sources

- bubbletea v2 RC: https://github.com/charmbracelet/bubbletea/tree/v2
- bubbles v2: https://github.com/charmbracelet/bubbles/tree/v2
- lipgloss v2: https://github.com/charmbracelet/lipgloss/tree/v2
- bubbletea-wm (IME reference): https://github.com/code-yeongyu/bubbletea-wm
- crush (production IME implementation): https://github.com/charmbracelet/crush
- go-runewidth: https://github.com/mattn/go-runewidth
- Unicode East Asian Width: https://www.unicode.org/reports/tr11/
