# Clojure Reference

Use for Clojure data, naming, project layout, error handling, `deps.edn`, REPL, idioms, performance, and anti-patterns.

## Data structures

- Indexed access/append: Vector `[]` (default sequence; O(~1) indexed access and append).
- Sequential prepend/stacks/recursion: List `'()`.
- Key-value associations: Map `{}`; keywords suit named fields.
- Membership, uniqueness, deduplication/filtering: Set `#{}`.
- FIFO: `clojure.lang.PersistentQueue/EMPTY`.
- Key order: `(sorted-map)`.
- Coordinates: vector/tuple as map key.

## Naming

```clojure
;; kebab-case for vars and functions
(def max-retry-attempts 3)
(defn calculate-total-price [items] ...)

;; Predicates end with ?
(defn valid-email? [email] ...)

;; Side-effecting functions end with !
(defn save-user! [user] ...)
(defn reset-counter! [] ...)

;; Dynamic vars use earmuffs
(def ^:dynamic *config* {...})

;; CamelCase for protocols and records
(defprotocol Storage ...)
(defrecord DatabaseStorage [conn] ...)

;; Private functions use defn-
(defn- parse [input] ...)      ; Internal helper
(defn process [data] ...)      ; Public API
```

## Practices

Do:
- Prefer pure functions: same input, same output, no side effects.
- Use immutable data and persistent structures.
- Use `->`/`->>` pipelines; destructure liberally; use keywords as functions (`(:name user)` rather than `(get user :name)`).
- Keep functions small, single-responsibility, and independently testable.
- Develop incrementally at the REPL and test immediately.
- Define specs for critical domain entities.

Avoid:
- Mutable state; use atoms/refs only when necessary.
- Deep nesting; use threading and small functions.
- Reinventing `clojure.core`/standard-library functionality.
- Overusing macros; functions are simpler, composable, and testable.
- Global state; pass dependencies explicitly or use dynamic vars.
- Ignoring laziness; distinguish lazy from realized sequences.

## REPL

```clojure
;; Reload namespace
(require '[myapp.core :as core] :reload)

;; Reload all dependencies
(require '[myapp.core :as core] :reload-all)

;; Inspect var metadata
(meta #'core/my-fn)

;; Find docs
(doc map)
(source map)
(apropos "str")

;; Pretty print
(clojure.pprint/pprint (complex-data))

;; Time execution
(time (expensive-operation))
```

## Performance

Avoid reflection (use `^String` type hints in hot paths), unnecessary lazy-sequence realization (use `first`, `take` when possible), repeated hash lookups (destructure once/use locals), and tight-loop boxing (use primitive type hints).

Prefer transducers for multi-step large-data transformations; reducers for parallel folds; persistent vectors over lists for random access; `into` over repeated `conj` for batching; `mapv`/`filterv` when vectors are required and intermediate lazy seqs are undesirable.

## Code organization

```text
src/
├── myapp/
│   ├── core.clj         ; Entry point, -main
│   ├── config.clj       ; Configuration loading
│   ├── domain/          ; Domain entities, specs
│   │   ├── user.clj
│   │   └── order.clj
│   ├── db/              ; Database access
│   │   └── queries.clj
│   └── api/             ; HTTP handlers
│       └── routes.clj
test/
├── myapp/
│   └── domain/
│       └── user_test.clj
```

## Idioms

```clojure
;; Safe navigation (nil-punning)
(some-> user :address :city str/upper-case)

;; Default values
(or (:name user) "Anonymous")
(:name user "Anonymous")  ; Same with get

;; Update multiple keys
(-> user
    (assoc :updated-at (java.util.Date.))
    (update :version inc))

;; Conditional update
(cond-> user
  admin? (assoc :role :admin)
  verified? (assoc :verified true))

;; Juxt for extracting multiple values
((juxt :name :email) user)  ; => ["Alice" "alice@ex.com"]

;; Frequencies for counting
(frequencies ["a" "b" "a" "c" "a"])
; => {"a" 3, "b" 1, "c" 1}

;; Group and transform
(->> items
     (group-by :category)
     (map-vals #(map :name %)))
```

## Errors

```clojure
;; Use ex-info for exceptions with data
(throw (ex-info "User not found" {:user-id id}))

;; Catch and extract data
(try
  (find-user id)
  (catch Exception e
    (let [{:keys [user-id]} (ex-data e)]
      (log/error "Failed for user:" user-id))))

;; Return result maps instead of exceptions
{:ok result}
{:error {:type :not-found :message "..."}}
```

## Project structure

```text
myapp/
├── deps.edn
├── build.clj               # tools.build script
├── src/
│   └── myapp/
│       ├── core.clj
│       └── db.clj
├── test/
│   └── myapp/
│       └── core_test.clj
└── resources/
```

## `deps.edn`

```clojure
{:paths ["src" "resources"]

 :deps
 {org.clojure/clojure {:mvn/version "1.12.0"}
  org.clojure/core.async {:mvn/version "1.6.681"}
  metosin/malli {:mvn/version "0.16.4"}}

 :aliases
 {;; Run application
  :run
  {:main-opts ["-m" "myapp.core"]}

  ;; REPL with rebel-readline
  :repl/rebel
  {:extra-deps {com.bhauman/rebel-readline {:mvn/version "0.1.4"}}
   :main-opts ["-m" "rebel-readline.main"]}

  ;; Testing with Kaocha
  :test/run
  {:extra-paths ["test"]
   :extra-deps {lambdaisland/kaocha {:mvn/version "1.91.1392"}}
   :exec-fn kaocha.runner/exec-fn
   :exec-args {:fail-fast? true}}

  ;; Build
  :build
  {:replace-paths ["."]
   :replace-deps {io.github.clojure/tools.build
                  {:git/tag "v0.10.5" :git/sha "2a21b7a"}}
   :ns-default build}

  ;; Linting
  :lint
  {:extra-deps {clj-kondo/clj-kondo {:mvn/version "2024.08.01"}}
   :main-opts ["-m" "clj-kondo.main" "--lint" "src" "test"]}

  ;; Outdated deps
  :search/outdated
  {:extra-deps {com.github.liquidz/antq {:mvn/version "2.8.1201"}}
   :main-opts ["-m" "antq.core"]}}}
```

## Dependency types

```clojure
;; Maven (most common)
{org.clojure/data.json {:mvn/version "2.5.0"}}

;; Git (latest or specific commit)
{io.github.user/lib {:git/tag "v1.0.0" :git/sha "abc1234"}}
{io.github.user/lib {:git/sha "abc1234def5678"}}

;; Local development
{mylib {:local/root "../mylib"}}
```

## Core patterns

### Pure functions and immutability

```clojure
;; Immutable by default
(defn update-user [user new-email]
  (assoc user :email new-email))  ; Returns new map

;; Transform, don't mutate
(update {:count 0} :count inc)    ; => {:count 1}
(update-in m [:user :age] inc)    ; Nested update
```

### Threading

```clojure
;; Thread-first: subject flows through
(-> user
    (assoc :updated-at (now))
    (update :login-count inc)
    validate
    save)

;; Thread-last: collection flows through
(->> numbers
     (filter even?)
     (map inc)
     (reduce +))

;; Conditional threading
(cond-> user
  admin? (assoc :role :admin)
  verified? (assoc :verified true))
```

### Destructuring

```clojure
;; Maps
(let [{:keys [name email]} user] ...)
(let [{:keys [name] :or {name "anon"}} user] ...)
(let [{:keys [name] :as user} data] ...)

;; Vectors
(let [[x y & rest] coords] ...)
(let [[_ second third] items] ...)

;; Function parameters
(defn greet [{:keys [name email]}]
  (format "Hello %s (%s)" name email))
```

### Higher-order functions

```clojure
;; Composition
(def process (comp str/upper-case str/trim))
(process "  hello  ")  ; => "HELLO"

;; Partial application
(def add-five (partial + 5))
(add-five 10)  ; => 15

;; Multiple transforms
((juxt :name :age) {:name "Alice" :age 30})
; => ["Alice" 30]
```

### Control flow

```clojure
;; when: single truthy branch
(when (valid? user)
  (save user))

;; if-let: bind and branch
(if-let [user (find-user id)]
  (process user)
  (handle-not-found))

;; case: compile-time constants (fast)
(case status
  :pending (handle-pending)
  :active (handle-active)
  (handle-unknown))

;; cond: complex conditions
(cond
  (neg? n) "negative"
  (pos? n) "positive"
  :else "zero")
```

## Anti-patterns

|Avoid|Do Instead|
|---|---|
|Mutable state everywhere|Use atoms sparingly, prefer pure functions|
|`(if (not x) ...)`|`(if-not x ...)` or `(when-not x ...)`|
|`(not (= a b))`|`(not= a b)`|
|`(first (filter pred coll))`|`(some pred coll)`|
|Deep nesting|Threading macros `->`, `->>`|
|`(into [] (map f coll))`|`(mapv f coll)`|
|String concatenation|`(str a b c)` or `(format ...)`|
|`(nth coll 0)`|`(first coll)`|
|Manual recursion|`reduce`, `iterate`, `loop/recur`|
|`def` inside functions|`let` bindings|
