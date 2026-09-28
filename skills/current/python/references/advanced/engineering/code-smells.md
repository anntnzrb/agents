# Code Smells: Reference

## Index

Read the section matching the task; search headings before loading unrelated detail.

On detection, **stop and re-examine the design**. A smell is not a syntax error: fix it when the task and project contract support the change; otherwise document a specific reason to carry it. Do not trigger an unrelated rewrite merely because a smell exists.

---

## Smell 1: Oversized module

### Why size matters

Line count is a proxy. For agents, a large file costs:

- Parallelism: a file is one edit boundary. Two agents cannot safely edit it at once, so one large file serializes work that separate modules would let run concurrently.
- Context: an open question ("where does X happen?") reads more of a large mixed file than of a module named for its responsibility.
- Stale reads: every edit changes the file's snapshot. A large shared file forces more re-reads and more edits against stale content.

Over-splitting also costs: tracing one flow across many tiny files, wrappers, and re-exports takes more reads than one cohesive file. Size alone never justifies a split; mixed responsibilities do.

### Measuring pure LOC

Pure LOC counts non-blank, non-comment lines.

```bash
# Quick (line-comment + blank exclusion):
awk '!/^[[:space:]]*$/ && !/^[[:space:]]*(\/\/|#|--)/' <file> | wc -l

# Authoritative (handles block comments correctly):
cloc --by-file <file>   # the "code" column is the number
```

### Thresholds

Thresholds apply to hand-written production code:

- Under about 800 pure LOC: no action.
- About 1,000 or more: review trigger. Check whether the file holds more than one responsibility.
- About 2,000 or more: it almost certainly does. Name the responsibilities and propose a split.

Tests may run longer because each case stands alone. Split a test file by subject under test or behavior cluster when it mixes unrelated subjects or several agents need to edit it at once.

### Required behavior

- **Creating code.** Carve by responsibility from the start: one cohesive unit per file. Do not create a file that already holds two responsibilities.
- **Editing a file past the review threshold.** Keep the change local. Do not split as a side effect of an unrelated task. Name the concrete split in your reply and ask whether to do it now.
- **Splitting, when the task asks for it.** Split along responsibilities, never mid-responsibility or by count (`foo_1.py`, `module_part_A.rs`, `service-2.ts`). Name each module for its role. No catch-all logic dumps (`utils.py`, `helpers.ts`, `common.py`, `shared.ts`). A barrel (`__init__.py`, `mod.rs`, `index.ts`) re-exports only; it never holds logic. Rerun tests, type checks, and lint afterwards.

### Exempt

- Generated code and build output
- Pure data tables: translation strings, error-code lookups, protocol models
- A truly indivisible single-responsibility unit, such as a parser table or a state machine whose states share one closure

### Concrete split examples

#### Python: BEFORE (`user_service.py`, five responsibilities)

```python
# user_service.py: DOES TOO MUCH
class UserRepository: ...        # 90 LOC of SQLAlchemy
class UserValidator: ...         # 60 LOC of Pydantic + business rules
class PasswordHasher: ...        # 40 LOC of bcrypt wrapper
class EmailSender: ...            # 50 LOC of httpx2 client
class UserService: ...           # 130 LOC orchestrating the four above
def _build_query(...): ...       # 25 LOC helper
def _format_email(...): ...      # 17 LOC helper
```

#### Python: AFTER (split by responsibility)

```
src/myapp/users/
├── __init__.py              # barrel: re-exports UserService only (5 LOC)
├── repository.py            # UserRepository                 (~95 LOC)
├── validator.py             # UserValidator                  (~65 LOC)
├── password.py              # PasswordHasher                 (~45 LOC)
├── notifier.py              # EmailSender (renamed; the role, not the verb)
├── service.py               # UserService (orchestrator)     (~135 LOC)
└── _queries.py              # _build_query (private)         (~30 LOC)
```

#### Rust: BEFORE (`auth.rs`, four responsibilities)

```rust
// auth.rs: DOES TOO MUCH
pub struct Session { ... }                      // 40 LOC
impl Session { ... }                            // 90 LOC of methods
pub struct TokenIssuer { ... }                  // 30 LOC
impl TokenIssuer { ... }                        // 70 LOC
pub struct RateLimiter { ... }                  // 50 LOC
impl RateLimiter { ... }                        // 70 LOC
fn parse_authorization_header(...) { ... }      // 30 LOC
```

#### Rust: AFTER

```
src/auth/
├── mod.rs              # re-exports Session, TokenIssuer, RateLimiter (8 LOC)
├── session.rs          # Session + impl                         (~130 LOC)
├── token.rs            # TokenIssuer + impl                     (~100 LOC)
├── rate_limit.rs       # RateLimiter + impl                     (~120 LOC)
└── header.rs           # parse_authorization_header             (~35 LOC)
```

#### TypeScript: BEFORE (`api/orders.ts`, five responsibilities)

```typescript
// api/orders.ts: DOES TOO MUCH
export const OrderSchema = z.object({ ... })          // 30 LOC
type Order = z.infer<typeof OrderSchema>
export class OrderRepository { ... }                  // 110 LOC
export class PricingEngine { ... }                    // 130 LOC
export class TaxCalculator { ... }                    // 90 LOC
export class OrderService { ... }                     // 150 LOC
```

#### TypeScript: AFTER

```
src/orders/
├── index.ts                    # barrel (6 LOC)
├── schema.ts                   # OrderSchema + Order type      (~35 LOC)
├── repository.ts               # OrderRepository               (~115 LOC)
├── pricing.ts                  # PricingEngine                 (~135 LOC)
├── tax.ts                      # TaxCalculator                 (~95 LOC)
└── service.ts                  # OrderService (orchestrator)   (~155 LOC)
```

---

## Smell 2: Function with more than 3 parameters

Parameters are the function’s contract with every caller. More than 3 independent inputs overwhelm working memory and signal either excessive function responsibility or related parameters that belong in a typed domain concept. Split the function or group related parameters. If 4+ inputs truly remain independent, justify WHY they cannot be grouped; “the function needs them all” is insufficient.

### Disguises that count as the same smell

**Dict/map smuggling:**

```python
# SMELL: hiding 6 args in a dict
def create_order(params: dict[str, Any]) -> Order: ...
```

```typescript
// SMELL: untyped options bag
function createOrder(opts: Record<string, unknown>): Order { ... }
```

```go
// SMELL: map instead of typed params
func CreateOrder(params map[string]any) (*Order, error) { ... }
```

**Variadic/kwargs catch-all:**

```python
# SMELL: hiding real params behind kwargs
def send_notification(recipient: str, **kwargs) -> None: ...
```

```typescript
// SMELL: rest params to avoid naming args
function sendNotification(recipient: string, ...args: unknown[]): void { ... }
```

**Config object wrapping positional args:**

```python
# SMELL: "options" object that exists only to bundle what would be positional args
@dataclass
class CreateUserOptions:
    name: str
    email: str
    password: str
    role: str
    department: str
    manager_id: int
    # 6 fields, used by exactly one function, no defaults


def create_user(opts: CreateUserOptions) -> User: ...
```

An options object is NOT a smell when it represents a genuine domain concept reused across multiple call sites with sensible defaults for most fields (e.g., `HttpClientConfig`, `DatabaseConnectionOptions`, `RetryPolicy`).

### Fix

Group related parameters into typed value objects with domain names:

```python
# CLEAN: grouped by domain concept
@dataclass(frozen=True, slots=True)
class UserIdentity:
    name: str
    email: str


@dataclass(frozen=True, slots=True)
class OrgPlacement:
    role: str
    department: str
    manager_id: int


def create_user(
    identity: UserIdentity, placement: OrgPlacement, password: str
) -> User: ...


# 3 params, each a meaningful concept
```

```typescript
// CLEAN: typed grouping
interface ShippingDetails {
  readonly address: string;
  readonly city: string;
  readonly zip: string;
  readonly country: string;
}

function createOrder(customer: CustomerId, items: readonly LineItem[], shipping: ShippingDetails): Order { ... }
// 3 params, shipping is a reusable domain type
```

```go
// CLEAN: struct with domain meaning
type Placement struct {
    Role       string
    Department string
    ManagerID  UserID
}

func CreateUser(identity UserIdentity, placement Placement, password string) (*User, error) { ... }
```

---

## Smell 3: Redundant verification after a destructive action

The contract of a destructive operation (`delete`, `remove`, `clear`, `drop`) IS verification: if it returns without error, the target is gone. Re-querying or asserting at the call site is dead code, misleading, and a performance waste. If the operation’s return cannot be trusted, fix the operation, not its caller. This is defensive bloat, not correctness.

```python
# SLOP: delete then verify deletion
db.delete(user)
db.commit()
remaining = db.query(User).filter_by(id=user.id).first()
assert remaining is None  # the ORM already guaranteed this

# CLEAN
db.delete(user)
db.commit()
```

```typescript
// SLOP: remove from array then check it's gone
items = items.filter(i => i.id !== targetId);
if (items.find(i => i.id === targetId)) {
  throw new Error("removal failed");  // impossible by construction
}

// CLEAN
items = items.filter(i => i.id !== targetId);
```

```go
// SLOP: delete row then SELECT to confirm
_, err := db.ExecContext(ctx, "DELETE FROM users WHERE id = $1", id)
if err != nil { return err }
row := db.QueryRowContext(ctx, "SELECT id FROM users WHERE id = $1", id)
if err := row.Scan(&check); err != sql.ErrNoRows {
    return fmt.Errorf("delete verification failed")
}

// CLEAN
_, err := db.ExecContext(ctx, "DELETE FROM users WHERE id = $1", id)
if err != nil { return err }
```

```rust
// SLOP: remove from HashMap then check absence
map.remove(&key);
if map.contains_key(&key) {
    panic!("removal failed");  // HashMap::remove is not broken
}

// CLEAN
map.remove(&key);
```

Same defect in any immediate postcondition check:

- setter → getter to confirm the value;
- file write → read to verify it;
- row insert → `SELECT` to confirm it;
- array push → `.length` increased by 1;
- assignment → assertion of the assigned value.

---

## Smell 4: Negative-form names and conditions

Negation forces mental inversion; double negatives (`if !isNotReady`) become logic and review hazards. Prefer naming the presence of the quality you care about, then invert branch logic as needed.

|Negative (SMELL)|Positive (CLEAN)|
|---|---|
|`isNotValid`|`isValid` (invert branch)|
|`isDisabled`|`isEnabled`|
|`noErrors`|`isClean` / `errorsResolved`|
|`notFound`|`found` (invert branch)|
|`isNotEmpty`|`hasItems` / `isPopulated`|
|`missingAuth`|`hasAuth` / `isAuthenticated`|
|`cannotProceed`|`canProceed` (invert branch)|

```python
# SMELL: double negative
if not is_invalid(token):
    proceed()

# CLEAN: single positive check
if is_valid(token):
    proceed()
```

```typescript
// SMELL: negated boolean in branch
if (!user.isNotVerified) {
  grantAccess();
}

// CLEAN: positive name, direct check
if (user.isVerified) {
  grantAccess();
}
```

```go
// SMELL: inverted negative
if !config.DisableLogging {
    log.Info("starting")
}

// CLEAN: positive flag
if config.LoggingEnabled {
    log.Info("starting")
}
```

```rust
// SMELL: negated negative
if !skip_validation {
    validate(&input)?;
}

// CLEAN: positive gate
if should_validate {
    validate(&input)?;
}
```

Negation IS appropriate for:

- early-return/guard clauses: `if !authorized { return Err(...) }`;
- filtering out: `items.filter(|x| !x.is_expired())`;
- inherently negative error states: `Error`, `Failed`, `Timeout` (do not force positive wrappers such as `isSuccessAbsent`).

The rule is not “never use negation”: when presence and absence are both viable names, name presence; branch logic follows from the name.
