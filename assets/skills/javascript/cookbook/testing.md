# JavaScript Testing Patterns

Read this file for runner choice, test structure, async tests, mocking, integration tests, fixtures, timers, and Testing Library patterns.

## Pick the runner from repo context

| Situation | Default |
| --- | --- |
| Vite / bundler repo with no runner yet | Vitest |
| Existing Jest repo / React Native / legacy ecosystem hooks | Jest |
| Browser UI behavior | Existing runner + Testing Library |
| HTTP / DB boundary tests | Existing runner + real integration setup |

Use the repo's current runner unless migration is the task.

## Test layers

- **Unit** - pure transforms, parser logic, small state machines
- **Integration** - HTTP handlers, DB repos, filesystem, queues, fetch wrappers
- **UI** - rendered behavior, accessibility, user flows

Test behavior at the lowest layer that still exposes the failure you care about.

## File structure and naming

- place tests next to source or under `__tests__/`; respect repo convention
- use `*.test.js` / `*.spec.js`
- group related cases with `describe()` when it improves scanability
- name tests by behavior, not implementation details

## Async tests

```js
import { describe, expect, it, vi } from "vitest";

it("rejects when the API returns 404", async () => {
  global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 404 });

  await expect(loadUser("missing")).rejects.toThrow("404");
});
```

Use `async` / `await` or returned Promises. Do not rely on hidden timing or `done()` unless the API genuinely requires callbacks.

## Mocking strategy

Mock external edges:
- network
- database
- filesystem
- time
- browser globals

Do **not** over-mock your own core logic. That creates tests for the mock graph instead of behavior.

### Dependency injection beats magic mocks

```js
export function createUserService({ repo, idFactory }) {
  return {
    async create(input) {
      const user = { id: idFactory(), ...input };
      await repo.save(user);
      return user;
    },
  };
}
```

```js
import { describe, expect, it, vi } from "vitest";

it("persists the created user", async () => {
  const repo = { save: vi.fn() };
  const service = createUserService({
    repo,
    idFactory: () => "u_1",
  });

  const user = await service.create({ name: "Ada" });

  expect(user).toEqual({ id: "u_1", name: "Ada" });
  expect(repo.save).toHaveBeenCalledWith(user);
});
```

### Module mocks

Use module mocks when DI is impractical or the repo already standardizes them.

```js
vi.mock("node:fs/promises", () => ({
  readFile: vi.fn(),
}));
```

Jest equivalent:

```js
jest.mock("node:fs/promises", () => ({
  readFile: jest.fn(),
}));
```

## Integration tests

Prefer real boundaries with test-only infrastructure over unit tests that pretend I/O works.

### HTTP example with `supertest`

```js
import request from "supertest";
import { app } from "../app.js";

it("creates a user", async () => {
  const response = await request(app)
    .post("/users")
    .send({ name: "Ada" })
    .expect(201);

  expect(response.body.name).toBe("Ada");
});
```

For DB integration tests:
- create or migrate the schema for tests
- isolate data per test or truncate tables between tests
- close pools / connections in teardown

## Testing Library

Prefer semantic queries over implementation details.

```js
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

it("submits the form", async () => {
  const onSubmit = vi.fn();
  render(<UserForm onSubmit={onSubmit} />);

  await userEvent.type(screen.getByLabelText(/name/i), "Ada");
  await userEvent.click(screen.getByRole("button", { name: /save/i }));

  expect(onSubmit).toHaveBeenCalledWith({ name: "Ada" });
});
```

Good query order:
1. `getByRole`
2. `getByLabelText`
3. `getByText`
4. `getByPlaceholderText`
5. `getByTestId` only when the UI has no better semantic handle

## Fixtures and factories

Prefer small factories with overrides.

```js
export function createUser(overrides = {}) {
  return {
    id: "u_1",
    name: "Ada",
    email: "ada@example.com",
    ...overrides,
  };
}
```

Factories keep tests focused on the fields that matter.

## Timers

Use fake timers only when time is part of the behavior.

```js
vi.useFakeTimers();
const fn = vi.fn();
const debounced = debounce(fn, 200);

debounced();
vi.advanceTimersByTime(199);
expect(fn).not.toHaveBeenCalled();

vi.advanceTimersByTime(1);
expect(fn).toHaveBeenCalledTimes(1);
```

Restore timers in teardown if the repo does not do it centrally.

## Snapshots

Use snapshots for stable structured output or small UI fragments. Keep them focused. Giant snapshots become ceremonial noise.

## Coverage

Coverage is a lagging indicator, not proof of correctness.

Good targets:
- error paths that actually matter
- serialization / parsing boundaries
- concurrency and timeout behavior
- regressions for previously broken cases

## Jest quick-reference

- module mock: `jest.mock()`
- spy: `jest.spyOn()`
- resolved Promise: `mockResolvedValue()`
- rejected Promise: `mockRejectedValue()`
- timer control: `jest.useFakeTimers()`

Vitest equivalents are the same shape under `vi.*`.
