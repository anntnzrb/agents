# Git hooks

These hooks enforce the sync application's local quality gates without an
external hook manager.

Enable them once after cloning:

```sh
git config --local core.hooksPath .githooks
```

Install the sync dependencies once per clone before committing:

```sh
cd sync && bun install --frozen-lockfile
```

This creates only `sync/node_modules/`, using the versions pinned by
`sync/bun.lock`; it does not install packages globally. The hooks perform this
same frozen local bootstrap automatically when an isolated commit or push
workflow does not contain the ignored `node_modules/` directory. They never
rewrite tracked source files.
