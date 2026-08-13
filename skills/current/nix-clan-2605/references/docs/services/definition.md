# Definition

`clanServices`: modular building blocks that simplify configuration and orchestration of multi-host services.

Each `clanService`:

* module of class `clan.service`
* can define roles, e.g. `client`, `server`
* uses `inventory.instances` to configure where and how it is deployed

:::admonition[Note]{type=note}
`clanServices`: part of Clan's next-generation service model; intended to replace `clanModules`.

See [Migration Guide](../guides/migrations/migrate-inventory-services.md) for migration help.
:::

See [Using clanServices guide](../guides/services/intro-to-services-revised.md) for practical usage.
