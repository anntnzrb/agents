# React performance updates

Read this reference before applying the older individual rules or the compiled guide. It captures newer upstream guidance and corrects examples that no longer reflect the recommended approach.

## Async work and bundles

- Check a cheap synchronous condition before awaiting a flag or remote value when their order has no required side effects. Keep the original order when the condition depends on the result or ordering matters.
- For partially dependent operations, start independent promises together and chain each dependent fetch to its own parent. A slow item must not prevent other items' nested fetches from starting.
- Keep dynamic import and filesystem paths statically analyzable. Use a map of functions with literal `import()` paths rather than dynamically composing import paths. Literal filesystem paths also keep server file tracing narrow.
- Prefer framework-supported package import optimization or documented typed subpath exports. The older guide's `lucide-react/dist/esm/icons/*` imports may lack declarations or be private.

## Server work

- Treat Server Actions as public endpoints. Validate input and authorize the mutation at the action or its server-only data boundary; follow `rules/server-auth-actions.md`.
- Keep request data out of mutable module-level variables. Concurrent server renders share process memory. Immutable static assets and correctly keyed shared caches are different: their contents must not leak request-specific data.
- Hoist immutable static file or asset loading when reuse is appropriate. Consider cold starts, memory usage, changes at runtime, and failures; never hoist request-specific or sensitive data into shared state.
- Avoid passing both an array and a copied or transformed version to the same client component when the client can derive it cheaply. RSC serialization can deduplicate shared references, not separately allocated arrays. Keep expensive transformations on the server when that tradeoff is better.
- `React.cache` compares each argument with `Object.is`: pass primitives or stable references to obtain cache hits. Next.js request memoization for `fetch` depends on the framework version and request options.
- For composition-based parallel fetching, do not await the header in the enclosing layout before rendering its children. Render an async header component as a sibling instead. The corrected example is in `rules/server-parallel-fetching.md`.

## Client and rendering

- Use passive listeners for touch or wheel events only when the handler never calls `preventDefault`. Clean up listeners on unmount.
- Version persisted `localStorage` formats, validate parsed values, handle unavailable storage and quota errors, and avoid storing sensitive or unnecessary data.
- Derive values during rendering rather than synchronizing redundant state in an effect. Put interaction-specific side effects in the corresponding event handler.
- Avoid defining component types inside render functions: a new type remounts the subtree and loses its state. Split unrelated effects or costly memoized computations when their dependencies differ.
- Do not memoize trivial primitive expressions by default. Hoist non-primitive defaults when their identity is passed to memoized children or used as a hook dependency; a default declared inside a memoized component does not by itself break `memo`'s prop comparison.
- Use `useDeferredValue` for expensive derived rendering when input responsiveness suffers; memoize the expensive work and ensure expensive child rendering can be skipped while the deferred value is unchanged. Use refs for frequently updated values that do not determine rendered UI.
- Use `useTransition` for non-urgent updates and its pending state when it models the interaction. It does not replace explicit loading state for every asynchronous operation.
- Use `suppressHydrationWarning` only for an unavoidable, understood mismatch, on the specific element. It suppresses a warning rather than fixing the mismatch and works only one level deep.
- Use `async` or `defer` for suitable non-critical classic scripts, accounting for ordering. Module scripts are deferred by default. Use React DOM resource hints when resource URLs and timing are known, and avoid unnecessary preloads.

## Browser work and effects

- Avoid layout thrashing: group DOM reads before writes. Batch style changes where practical.
- Use `flatMap` to combine mapping and filtering when it improves clarity, not as a blanket performance claim. In hot paths, measure against a loop.
- Schedule non-critical work with `requestIdleCallback` when supported, with a fallback and cleanup. Do not defer required work indefinitely.
- Initialize app-wide work at the appropriate app boundary rather than on every component mount. Account for server rendering, multiple roots, hot reloads, and development Strict Mode.
- Where supported, use `useEffectEvent` for non-reactive logic called from an effect. Do not put an Effect Event in a dependency array or use it to hide reactive dependencies. On older React versions, the existing ref pattern may be appropriate.
