# Clojure Testing Cookbook

Clojure testing recipes: `clojure.test`, Kaocha, `test.check`. Covers unit tests, fixtures, async checks, Kaocha configuration, and generative tests.

## Basic Unit Tests

`testing` groups related assertions and improves failure context.

```clojure
(ns myapp.core-test
  (:require [clojure.test :refer [deftest is testing are]]
            [myapp.core :as core]))

;; Simple test
(deftest test-add
  (is (= 3 (core/add 1 2))))

;; Grouped assertions
(deftest test-calculation
  (testing "addition"
    (is (= 3 (core/add 1 2)))
    (is (= 0 (core/add 0 0))))
  (testing "multiplication"
    (is (= 6 (core/multiply 2 3)))
    (is (= 0 (core/multiply 0 5)))))
```

## Assertion Types

```clojure
;; Equality
(is (= expected actual))

;; Truthiness
(is (true? value))
(is (false? value))
(is (nil? value))
(is (some? value))

;; Type checking
(is (vector? value))
(is (instance? Exception value))

;; Exception testing
(is (thrown? ArithmeticException (/ 1 0)))
(is (thrown-with-msg? Exception #"not found" (find-missing)))

;; Custom message
(is (= 4 (+ 2 2)) "Math is broken!")
```

Add custom assertion messages, especially for complex scenarios.

## Table-Driven Tests

`are` tests one pattern against multiple input/output rows; first row defines the pattern.

```clojure
(deftest test-fizzbuzz
  (are [n expected]
    (= expected (fizzbuzz n))
    1  "1"
    3  "Fizz"
    5  "Buzz"
    15 "FizzBuzz"
    30 "FizzBuzz"))
```

## Fixtures

`:each` runs setup/teardown per test; `:once` shares expensive setup across a namespace. `compose-fixtures` combines fixtures.

```clojure
;; Per-test fixture
(defn setup-fixture [f]
  (println "Setup")
  (f)  ; Run the test
  (println "Teardown"))

(use-fixtures :each setup-fixture)

;; Per-namespace fixture
(defn db-fixture [f]
  (with-open [conn (connect-db)]
    (binding [*db* conn]
      (f))))

(use-fixtures :once db-fixture)

;; Composing fixtures
(use-fixtures :each
  (compose-fixtures setup-fixture logging-fixture))
```

## Async Tests

Always use timeouts when dereferencing promises or blocking on channels; otherwise tests can hang indefinitely.

```clojure
;; Test async with promises
(deftest test-async-operation
  (let [p (promise)]
    (async-fn #(deliver p %))
    (is (= :expected (deref p 1000 :timeout)))))

;; Test core.async
(require '[clojure.core.async :as a])

(deftest test-channel
  (let [ch (a/chan)
        result (a/go
                 (a/>! ch :value)
                 (a/<! ch))]
    (is (= :value (a/<!! result)))))
```

## Kaocha Configuration

Separate aliases for one-shot and watch runs; watch mode reruns tests when files change.

```clojure
;; deps.edn
{:aliases
 {:test/run
  {:extra-paths ["test"]
   :extra-deps {lambdaisland/kaocha {:mvn/version "1.91.1392"}}
   :exec-fn kaocha.runner/exec-fn
   :exec-args {:fail-fast? true}}

  :test/watch
  {:extra-paths ["test"]
   :extra-deps {lambdaisland/kaocha {:mvn/version "1.91.1392"}}
   :exec-fn kaocha.runner/exec-fn
   :exec-args {:watch? true :fail-fast? true}}}}
```

```clojure
;; tests.edn
#kaocha/v1
{:tests [{:id :unit
          :test-paths ["test"]
          :source-paths ["src"]}]

 :plugins [:kaocha.plugin/capture-output
           :kaocha.plugin/profiling]

 :capture-output? true
 :fail-fast? true
 :color? true}
```

## Run Kaocha

```bash
# Run all tests
clojure -X:test/run

# Watch mode
clojure -X:test/run :watch? true

# Specific namespace
clojure -X:test/run :focus '[:unit myapp.core-test]'

# Fail fast
clojure -X:test/run :fail-fast? true

# Skip slow tests
clojure -X:test/run :skip-meta :slow
```

Use `:fail-fast? true` during development to stop at the first failure.

## Metadata Filters

Tag slow tests with `^:slow`; skip them during regular development and include them in CI. Use `--skip-meta :slow` or `--focus-meta :slow`.

```clojure
;; Mark slow tests
(deftest ^:slow test-integration
  (is (= :ok (slow-operation))))

;; Skip with --skip-meta :slow
;; Run only with --focus-meta :slow

;; Mark with multiple tags
(deftest ^:slow ^:integration ^:db test-db
  ...)
```

## Test Data Builders

Builders provide sensible defaults and customization; override only fields relevant to each test.

```clojure
(defn make-user
  ([] (make-user {}))
  ([overrides]
   (merge {:id (random-uuid)
           :name "Test User"
           :email "test@example.com"
           :created-at (java.util.Date.)}
          overrides)))

(deftest test-with-builder
  (let [admin (make-user {:role :admin})]
    (is (= :admin (:role admin)))))
```

## Side Effects

`with-redefs` temporarily replaces functions; capture effects in atoms or return fixed external-dependency values.

```clojure
;; Capture side effects
(deftest test-logging
  (let [logs (atom [])]
    (with-redefs [log/info (fn [& args] (swap! logs conj args))]
      (do-something)
      (is (= [["Operation complete"]] @logs)))))

;; Mock external calls
(deftest test-api-call
  (with-redefs [http/get (fn [_] {:status 200 :body "{}"})]
    (is (= :ok (fetch-data)))))
```

## Exceptions

Use `ex-data` inspection for error details beyond type and message.

```clojure
(deftest test-validation-errors
  ;; Throws any exception
  (is (thrown? Exception (validate nil)))

  ;; Throws with message pattern
  (is (thrown-with-msg? IllegalArgumentException
                        #"must be positive"
                        (validate -1)))

  ;; Capture and inspect exception
  (let [ex (try
             (validate nil)
             (catch Exception e e))]
    (is (= ::validation-error (-> ex ex-data :type)))
    (is (contains? (ex-data ex) :field))))
```

## Private Functions

Prefer testing through the public API; direct private-var access is possible:

```clojure
;; Access private var
(deftest test-private
  (let [private-fn #'myapp.core/private-helper]
    (is (= :expected (private-fn :input)))))

;; Better: test through public API
```

## Property-Based Tests

Use properties for invariants such as idempotency, commutativity, and round trips. The `defspec` count (`100` here) sets generated test cases.

```clojure
(require '[clojure.test.check :as tc]
         '[clojure.test.check.generators :as gen]
         '[clojure.test.check.properties :as prop]
         '[clojure.test.check.clojure-test :refer [defspec]])

(defspec test-reverse-idempotent 100
  (prop/for-all [v (gen/vector gen/int)]
    (= v (reverse (reverse v)))))

(defspec test-sort-idempotent 100
  (prop/for-all [v (gen/vector gen/int)]
    (= (sort v) (sort (sort v)))))
```

## Custom Generators

Compose simple generators with `gen/hash-map`, `gen/vector`, and other combinators; constrain with `gen/not-empty` and `gen/choose`.

```clojure
;; Composite generator
(def user-gen
  (gen/hash-map
    :id gen/uuid
    :name (gen/not-empty gen/string-alphanumeric)
    :age (gen/choose 0 120)))

(defspec test-user-processing 50
  (prop/for-all [user user-gen]
    (let [result (process-user user)]
      (and (contains? result :processed)
           (= (:id user) (:id result))))))
```

## Test Organization

Mirror `src` structure in `test`, use `_test.clj`, and keep shared fixtures/helpers in separate directories.

```text
test/
├── myapp/
│   ├── core_test.clj
│   ├── db_test.clj
│   ├── api_test.clj
│   └── integration_test.clj
├── fixtures/
│   └── sample_data.clj
└── helpers/
    └── test_utils.clj
```

```clojure
;; Unit tests mirror source structure
;; src/myapp/core.clj -> test/myapp/core_test.clj

(ns myapp.core-test
  (:require [clojure.test :refer :all]
            [myapp.core :as core]
            [myapp.test-helpers :as h]))
```

## Shared Test Utilities

Use a dedicated helper namespace for shared fixtures, builders, and macros; this reduces duplication and improves maintainability.

```clojure
;; test/myapp/test_helpers.clj
(ns myapp.test-helpers
  (:require [clojure.test :refer :all]))

(defn with-test-db [f]
  (let [db (create-test-db)]
    (try
      (binding [*db* db]
        (f))
      (finally
        (destroy-test-db db)))))

(defmacro with-timeout [ms & body]
  `(let [f# (future ~@body)]
     (deref f# ~ms :timeout)))
```
