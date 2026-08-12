# Clanlib

`clanLib`: functions and utilities.

:::admonition[Danger]{type=danger}
All ClanLib items internal to `clan-core` unless explicitly mentioned.
:::

## Stable Attributes

Publicly maintained:

### `clanLib.clan`

Function taking [Clan options](https://clan.lol/docs/26.05/reference/options/clan); option definitions composable via `imports`.

Returns evaluated Clan configuration, a `lib.evalModules` result:

- `.config`: main result.
- `.options`, `.moduleGraph`, and other fields: debugging.
