import type { MarketplaceAdapter, MarketplaceId } from "#models";

const adaptersRegistry = new Map<MarketplaceId, MarketplaceAdapter>();

/**
 * Register a marketplace adapter into the dynamic registry.
 */
export function registerAdapter(adapter: MarketplaceAdapter): void {
  adaptersRegistry.set(adapter.id, adapter);
}

/**
 * Unregister a marketplace adapter by ID.
 */
export function unregisterAdapter(id: MarketplaceId): boolean {
  return adaptersRegistry.delete(id);
}

/**
 * Get all currently registered marketplace adapters.
 */
export function getAvailableAdapters(): readonly MarketplaceAdapter[] {
  return Array.from(adaptersRegistry.values());
}

/**
 * Resolve which adapters to execute based on an optional filter list.
 * If filter is omitted or empty, returns all adapters with isEnabledByDefault: true.
 */
export function resolveAdapters(filter?: readonly string[]): readonly MarketplaceAdapter[] {
  if (!filter || filter.length === 0) {
    return getAvailableAdapters().filter((a) => a.isEnabledByDefault);
  }

  const normalized = filter.map((f) => f.trim().toLowerCase());
  const resolved: MarketplaceAdapter[] = [];

  for (const name of normalized) {
    for (const [id, adapter] of adaptersRegistry.entries()) {
      if (id.toLowerCase() === name || adapter.displayName.toLowerCase().includes(name)) {
        if (!resolved.some((r) => r.id === adapter.id)) {
          resolved.push(adapter);
        }
      }
    }
  }

  return resolved.length > 0 ? resolved : getAvailableAdapters().filter((a) => a.isEnabledByDefault);
}

/**
 * Clear all registered adapters (useful for test isolation).
 */
export function clearRegistry(): void {
  adaptersRegistry.clear();
}
