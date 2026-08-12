# clojure.spec Cookbook

Clojure `clojure.spec.alpha` cookbook: validation, generative testing, conforming, runtime checking, custom generation, and organization.

## Setup

```clojure
(require '[clojure.spec.alpha :as s]
         '[clojure.spec.gen.alpha :as gen]
         '[clojure.spec.test.alpha :as stest])
```

## Predicates and enums

```clojure
;; Define specs with predicates
(s/def ::age (s/and int? #(>= % 0) #(< % 150)))
(s/def ::name (s/and string? #(not (empty? %))))
(s/def ::email (s/and string? #(re-matches #".+@.+\..+" %)))

;; Using built-in predicates
(s/def ::id uuid?)
(s/def ::score double?)
(s/def ::active? boolean?)

;; Validate
(s/valid? ::age 25)     ; => true
(s/valid? ::age -5)     ; => false
(s/valid? ::age "25")   ; => false

;; Get explanation
(s/explain ::age -5)
; -5 - failed: (>= % 0) spec: :user/age

;; Get explanation data
(s/explain-data ::age -5)
; {:clojure.spec.alpha/problems [...] ...}
```

Use `s/explain` for development diagnostics; use `s/explain-data` for programmatic production errors.

```clojure
(s/def ::status #{:pending :active :done :cancelled})
(s/def ::color #{:red :green :blue})

(s/valid? ::status :active)  ; => true
(s/valid? ::status :unknown) ; => false
```

## Nil and maps

```clojure
(s/def ::optional-name (s/nilable string?))

(s/valid? ::optional-name nil)     ; => true
(s/valid? ::optional-name "Alice") ; => true
```

Use `s/nilable` for a value that can be absent or explicitly `nil`; use `:opt` in `s/keys` for optional map keys.

```clojure
;; Required and optional keys (qualified)
(s/def ::user
  (s/keys :req [::id ::name ::email]
          :opt [::age ::phone]))

;; Unqualified keys (for external data like JSON)
(s/def ::api-user
  (s/keys :req-un [::id ::name ::email]
          :opt-un [::age]))

;; Validates both structure AND value specs
(s/valid? ::user
  {::id (random-uuid)
   ::name "Alice"
   ::email "alice@example.com"})
; => true

;; Missing required key
(s/explain ::user {::name "Alice"})
; ... missing required keys: [:user/id :user/email]
```

Use `:req-un`/`:opt-un` for unqualified external/API/JSON keys.

## Collections

```clojure
;; Homogeneous collection
(s/def ::numbers (s/coll-of int?))
(s/def ::user-ids (s/coll-of uuid? :kind set?))
(s/def ::scores (s/coll-of double? :min-count 1 :max-count 100))

;; Vector specifically
(s/def ::point (s/coll-of number? :kind vector? :count 3))

;; Map of specific key/value types
(s/def ::config (s/map-of keyword? string?))

;; Tuples (fixed-size heterogeneous)
(s/def ::name-age (s/tuple string? int?))
(s/valid? ::name-age ["Alice" 30]) ; => true
```

`:kind` restricts collection type (`vector?`, `set?`, `list?`); `:min-count`, `:max-count`, and `:count` constrain size.

## Sequence regex and alternatives

```clojure
;; cat: concatenation (named parts)
(s/def ::http-request
  (s/cat :method #{:get :post :put :delete}
         :url string?
         :body (s/? map?)))  ; optional

(s/conform ::http-request [:get "/api/users"])
; => {:method :get :url "/api/users"}

(s/conform ::http-request [:post "/api/users" {:name "Alice"}])
; => {:method :post :url "/api/users" :body {:name "Alice"}}

;; alt: alternatives
(s/def ::id-or-name
  (s/alt :id int?
         :name string?))

(s/conform ::id-or-name [42])
; => [:id 42]

;; *: zero or more
(s/def ::args (s/* string?))

;; +: one or more
(s/def ::args+ (s/+ string?))

;; ?: zero or one
(s/def ::maybe-int (s/? int?))
```

`s/cat`, `s/alt`, `s/*`, `s/+`, and `s/?` validate sequences; `s/conform` returns structured data.

```clojure
;; s/or: labeled alternatives
(s/def ::name-or-id
  (s/or :name string?
        :id int?))

(s/conform ::name-or-id "Alice")  ; => [:name "Alice"]
(s/conform ::name-or-id 42)       ; => [:id 42]

;; s/and: all must pass
(s/def ::big-even
  (s/and int?
         even?
         #(> % 1000)))
```

`s/or` returns tagged tuples `[tag value]`; `s/and` requires every predicate.

## Function contracts and runtime checking

```clojure
(defn calculate-discount [price percentage]
  (* price (- 1 (/ percentage 100.0))))

(s/fdef calculate-discount
  :args (s/cat :price (s/and number? pos?)
               :percentage (s/int-in 0 101))
  :ret (s/and number? #(>= % 0))
  :fn (fn [{:keys [args ret]}]
        (<= ret (:price args))))

;; Check function manually
(s/valid? (:args (s/get-spec `calculate-discount))
          [100 20])
; => true
```

`:fn` checks relationships between arguments and return value.

```clojure
;; Turn on runtime checking (dev only!)
(stest/instrument `calculate-discount)

(calculate-discount 100 20)  ; Works
(calculate-discount -100 20) ; Throws spec error!

;; Turn off
(stest/unstrument `calculate-discount)

;; Instrument all
(stest/instrument)
```

Instrumentation is development-only: it adds runtime overhead and MUST NOT ship to production.

## Sample and property-based data

```clojure
;; Generate sample values
(gen/sample (s/gen ::age) 5)
; => (0 1 0 2 4)

(gen/sample (s/gen ::status) 5)
; => (:pending :active :done :pending :cancelled)

(gen/sample (s/gen ::user) 3)
; => ({:user/id #uuid "..." :user/name "Fy" ...} ...)

;; Exercise: generate and conform
(s/exercise ::name-or-id 5)
; => ([("" "") [:name ""]] [("a") [:name "a"]] ...)
```

`gen/sample` gives quick samples; `s/exercise` shows generated and conformed values. Specs automatically generate sample data.

```clojure
(require '[clojure.test.check.clojure-test :refer [defspec]]
         '[clojure.test.check.properties :as prop])

;; Test function against spec
(defspec test-calculate-discount 100
  (prop/for-all [price (s/gen (s/and number? pos?))
                 pct (s/gen (s/int-in 0 101))]
    (let [result (calculate-discount price pct)]
      (and (>= result 0)
           (<= result price)))))

;; Run spec check
(stest/check `calculate-discount)
```

Property-based testing finds edge cases with generated inputs; `stest/check` tests function specs.

## Custom generators

```clojure
;; Override default generator
(s/def ::email
  (s/with-gen
    (s/and string? #(re-matches #".+@.+\..+" %))
    #(gen/fmap
       (fn [[user domain tld]]
         (str user "@" domain "." tld))
       (gen/tuple
         (gen/such-that not-empty gen/string-alphanumeric)
         (gen/such-that not-empty gen/string-alphanumeric)
         (gen/elements ["com" "org" "net"])))))

;; Generator from fn
(s/def ::timestamp
  (s/with-gen
    inst?
    #(gen/fmap
       (fn [ms] (java.util.Date. ms))
       (gen/choose 0 (System/currentTimeMillis)))))
```

Use `s/with-gen` for domain-specific generators; `gen/fmap`, `gen/tuple`, and `gen/such-that` compose complex generators.

## Polymorphic data

```clojure
;; Dispatch on :type field
(defmulti event-type :type)

(defmethod event-type :login [_]
  (s/keys :req-un [::type ::user-id ::timestamp]))

(defmethod event-type :purchase [_]
  (s/keys :req-un [::type ::user-id ::item-id ::amount]))

(defmethod event-type :logout [_]
  (s/keys :req-un [::type ::user-id]))

(s/def ::event (s/multi-spec event-type :type))

;; Validates based on :type
(s/valid? ::event
  {:type :login
   :user-id "u123"
   :timestamp (java.util.Date.)})
; => true

(s/valid? ::event
  {:type :purchase
   :user-id "u123"
   :item-id "i456"
   :amount 99.99})
; => true
```

`s/multi-spec` plus multimethods selects validation by discriminator, useful for events or commands.

## Conform and unform

```clojure
;; conform: validate and transform
(s/conform ::name-or-id "Alice")
; => [:name "Alice"]

;; Invalid returns :clojure.spec.alpha/invalid
(s/conform ::age "not-a-number")
; => :clojure.spec.alpha/invalid

;; Check conformity
(let [result (s/conform ::age 25)]
  (if (= result ::s/invalid)
    (println "Invalid!")
    (println "Valid:" result)))

;; unform: reverse conform
(s/unform ::name-or-id [:name "Alice"])
; => "Alice"
```

`s/conform` returns transformed/tagged data or `::s/invalid`; use it to parse/destructure validated data. `s/unform` reverses the transformation.

## Organize specs

```clojure
;; specs.clj - Central spec definitions
(ns myapp.specs
  (:require [clojure.spec.alpha :as s]))

;; Domain specs
(s/def ::user-id uuid?)
(s/def ::username (s/and string? #(re-matches #"[a-z0-9_]{3,20}" %)))
(s/def ::email (s/and string? #(re-matches #".+@.+\..+" %)))

;; Entity specs
(s/def ::user
  (s/keys :req [::user-id ::username ::email]
          :opt [::display-name ::avatar-url]))

;; API specs (unqualified for JSON)
(s/def ::api-user
  (s/keys :req-un [::user-id ::username ::email]
          :opt-un [::display-name ::avatar-url]))
```

Keep domain specs in a dedicated namespace (for example, `myapp.specs`), defining primitives before composing entities.

## Validation helpers

```clojure
(defn validate! [spec data]
  (if (s/valid? spec data)
    data
    (throw (ex-info "Validation failed"
                    {:spec spec
                     :problems (s/explain-data spec data)}))))

(defn validate [spec data]
  (if (s/valid? spec data)
    {:ok data}
    {:error (s/explain-str spec data)}))
```

Use `validate!` to throw and `validate` to return result maps.

## Assertions

```clojure
;; Enable spec assertions
(s/check-asserts true)

;; Use in code
(defn process-user [user]
  (s/assert ::user user)
  ;; ... process ...
  )

;; Throws detailed error if invalid
```

Enable `s/check-asserts` in development; disable it in production for performance. `s/assert` throws detailed spec errors.
