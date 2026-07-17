# Vendored Shortcuts artifact pipeline

This skill includes a deliberately narrow, modified subset of
[`viticci/shortcuts-playground-plugin`](https://github.com/viticci/shortcuts-playground-plugin),
commit `2de03bffe4ce8802e06d184931d9e4ec366a2ef2` (2026-06-15):

- `scripts/validate_shortcut.py`
- `scripts/sign_shortcut.py`
- `scripts/select_shortcut_icon_color.py`
- required JSON catalogs in `data/`

Excluded on purpose: plugin manifests, hooks, visual assets, golden shortcuts,
and prose/reference documentation. Local inspector and blueprint scripts
predate this vendoring and are not derived from that project.

`validate_shortcut.py` and `select_shortcut_icon_color.py` stay outside local
Pyright ownership checks because they are vendored upstream code. Their runtime
behavior is covered by focused integration tests in `tests/`.

Copyright (c) 2026 Federico Viticci / MacStories

MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
