# Functional Patterns & Data Structures Cookbook

Clojure collection choice, sequence transforms, grouping, search, laziness, transducers, reducers, comprehensions, map transforms, and zippers.

## Choosing the Right Collection

Vectors: indexed access and append at end; lists: efficient prepend and sequential access; maps: key-value lookup; sets: membership testing and uniqueness.

```clojure
;; Vectors: indexed access, append at end
(def users ["Alice" "Bob" "Charlie"])
(get users 0)       ; => "Alice"
(conj users "Dave") ; => ["Alice" "Bob" "Charlie" "Dave"]
(nth users 1)       ; => "Bob"

;; Lists: prepend efficient, sequential access
(def queue '(1 2 3))
(cons 0 queue)      ; => (0 1 2 3)
(conj queue 0)      ; => (0 1 2 3) - prepends!

;; Maps: key-value lookup
(def user {:id 1 :name "Alice" :email "a@ex.com"})
(:name user)        ; => "Alice" (keyword as fn)
(get user :missing "default") ; => "default"

;; Sets: membership testing, uniqueness
(def tags #{"clojure" "functional" "jvm"})
(contains? tags "clojure") ; => true
(tags "clojure")           ; => "clojure" (set as fn)
```

Use `conj` for collection-appropriate addition, `assoc` for maps, and `merge-with` for conflict resolution.

```clojure
;; Adding
(conj [1 2] 3)           ; => [1 2 3]
(conj #{1 2} 3)          ; => #{1 2 3}
(assoc {:a 1} :b 2)      ; => {:a 1 :b 2}

;; Removing
(disj #{1 2 3} 2)        ; => #{1 3}
(dissoc {:a 1 :b 2} :a)  ; => {:b 2}
(pop [1 2 3])            ; => [1 2]

;; Combining
(concat [1 2] [3 4])     ; => (1 2 3 4)
(merge {:a 1} {:b 2})    ; => {:a 1 :b 2}
(merge-with + {:a 1} {:a 2}) ; => {:a 3}

;; Transforming
(mapv inc [1 2 3])       ; => [2 3 4] (eager vector)
(filterv even? [1 2 3 4]); => [2 4]
(reduce + [1 2 3 4])     ; => 10
```

## Keywords as Functions

Keywords extract map values and accept an optional default; sets implement `IFn` and work as predicates.

```clojure
;; Keywords extract from maps
(:name {:name "Alice" :age 30}) ; => "Alice"
(:missing {:name "Alice"})      ; => nil
(:missing {:name "Alice"} "?")  ; => "?"

;; Sets as predicates
(filter #{:a :b} [:a :b :c :d]) ; => (:a :b)
(remove #{:skip :ignore} items)
```

## Core Sequence Transformations

`map` transforms elements, `filter` selects, `reduce` aggregates, and `take`/`drop` select subsequences.

```clojure
;; map: transform each element
(map inc [1 2 3])          ; => (2 3 4)
(map :name users)          ; => ("Alice" "Bob")
(map vector [:a :b] [1 2]) ; => ([:a 1] [:b 2])

;; filter/remove: select elements
(filter even? [1 2 3 4])   ; => (2 4)
(remove nil? [1 nil 2])    ; => (1 2)
(filter :active users)     ; truthy :active

;; reduce: fold to single value
(reduce + [1 2 3 4])       ; => 10
(reduce + 100 [1 2 3])     ; => 106 (with init)
(reduce conj [] [1 2 3])   ; => [1 2 3]

;; take/drop: subsequences
(take 3 (range 10))        ; => (0 1 2)
(drop 3 (range 10))        ; => (3 4 5 6 7 8 9)
(take-while pos? [2 1 0 -1]) ; => (2 1)
```

## Grouping and Partitioning

`group-by` categorizes items by a key function; `partition` makes fixed-size chunks, `partition-all` keeps an incomplete final chunk, and `partition-by` splits when a function’s return value changes.

```clojure
;; group-by: map of key -> items
(group-by :type [{:type :a :n 1} {:type :b :n 2} {:type :a :n 3}])
; => {:a [{:type :a :n 1} {:type :a :n 3}]
;     :b [{:type :b :n 2}]}

;; partition: fixed-size chunks
(partition 2 [1 2 3 4 5])     ; => ((1 2) (3 4))
(partition 2 1 [1 2 3 4])     ; => ((1 2) (2 3) (3 4)) step=1
(partition-all 2 [1 2 3 4 5]) ; => ((1 2) (3 4) (5))

;; partition-by: chunk by fn
(partition-by even? [1 3 2 4 5])
; => ((1 3) (2 4) (5))
```

## Finding and Testing Elements

`some` returns the first truthy result, not necessarily `true`; `every?`, `not-every?`, and `not-any?` test predicates.

```clojure
;; some: find first truthy
(some even? [1 3 5 6])       ; => true
(some #{:a :b} [:c :a :d])   ; => :a
(some #(when (> % 5) %) [1 3 7 9]) ; => 7

;; every?/not-every?
(every? even? [2 4 6])       ; => true
(not-every? even? [2 3 4])   ; => true

;; not-any?
(not-any? even? [1 3 5])     ; => true
```

## Creating Lazy Sequences

`range`, `repeat`, `cycle`, `iterate`, and `lazy-seq` create lazy sequences; evaluation occurs only when needed. Limit infinite sequences with `take` or similar.

```clojure
;; range: lazy infinite or bounded
(range)           ; infinite: 0, 1, 2, ...
(range 5)         ; => (0 1 2 3 4)
(range 1 10 2)    ; => (1 3 5 7 9)

;; repeat/cycle
(take 3 (repeat :x))      ; => (:x :x :x)
(take 5 (cycle [:a :b]))  ; => (:a :b :a :b :a)

;; iterate: f(x), f(f(x)), ...
(take 5 (iterate inc 0))  ; => (0 1 2 3 4)
(take 5 (iterate #(* 2 %) 1)) ; => (1 2 4 8 16)

;; lazy-seq: custom lazy
(defn fibs
  ([] (fibs 0 1))
  ([a b] (lazy-seq (cons a (fibs b (+ a b))))))
(take 10 (fibs)) ; => (0 1 1 2 3 5 8 13 21 34)
```

## Realizing Lazy Sequences

Use `doall` when the realized sequence is needed, `dorun` for side effects only, and `vec`/`into` to produce concrete collections. Most lazy seqs are chunked 32 elements at a time for performance.

```clojure
;; Force evaluation
(doall (map println [1 2 3])) ; Realizes, returns seq
(dorun (map println [1 2 3])) ; Realizes, returns nil
(vec lazy-seq)                ; Realizes into vector
(into [] lazy-seq)            ; Same

;; Chunked sequences (32 elements at a time)
;; Most lazy seqs are chunked for performance
```

## Composable Transducers

Transducers separate transformation from data source, avoid intermediate sequences, compose with `comp`, and work with collections, channels, and reducers.

```clojure
;; Transducers separate transformation from data source
(def xf
  (comp
    (filter even?)
    (map inc)
    (take 5)))

;; Apply to different contexts
(into [] xf (range 100))           ; => [1 3 5 7 9]
(transduce xf + (range 100))       ; => 25
(sequence xf (range 100))          ; lazy seq

;; With core.async channels
(require '[clojure.core.async :as a])
(def ch (a/chan 10 xf))
```

## Common Transducer Operations

Most core sequence functions have transducer arities when called with parameters only.

```clojure
(map f)           ; Transform
(filter pred)     ; Keep matching
(remove pred)     ; Remove matching
(take n)          ; First n
(drop n)          ; Skip first n
(take-while pred) ; Until pred false
(drop-while pred) ; Skip until pred false
(dedupe)          ; Remove consecutive dups
(distinct)        ; Remove all dups
(partition-all n) ; Chunk into vectors
(cat)             ; Flatten one level
(mapcat f)        ; map + flatten
```

## Parallel Reducers

Reducers use Java’s fork/join for parallel processing; parallelism is beneficial only for large collections because of overhead.

```clojure
(require '[clojure.core.reducers :as r])

;; Parallel fold (for large collections)
(r/fold + (r/map inc (r/filter even? large-vec)))

;; fold with combiner
(r/fold
  (fn ([] {})              ; init
      ([a b] (merge a b))) ; combine
  (fn [acc x]              ; reduce
    (assoc acc x true))
  large-coll)
```

## For Comprehensions

`for` is lazy; use `:when` for filtering, `:let` for intermediate bindings, and `:while` for early termination.

```clojure
;; List comprehension
(for [x [1 2 3]
      y [:a :b]]
  [x y])
; => ([1 :a] [1 :b] [2 :a] [2 :b] [3 :a] [3 :b])

;; With :when filter
(for [x (range 10)
      :when (even? x)]
  (* x x))
; => (0 4 16 36 64)

;; With :let binding
(for [x [1 2 3]
      :let [y (* x x)]
      :when (> y 1)]
  y)
; => (4 9)

;; With :while early termination
(for [x (range 10)
      :while (< x 5)]
  x)
; => (0 1 2 3 4)
```

## Transforming Maps

Use `update-vals`/`update-keys` for bulk transformations, `select-keys` for projection, and custom merge functions for nested structures.

```clojure
;; Update values
(update-vals {:a 1 :b 2} inc)     ; => {:a 2 :b 3}
(update-keys {:a 1 :b 2} name)    ; => {"a" 1 "b" 2}

;; Select/rename keys
(select-keys {:a 1 :b 2 :c 3} [:a :b]) ; => {:a 1 :b 2}
(clojure.set/rename-keys {:a 1} {:a :alpha}) ; => {:alpha 1}

;; Deep merge
(defn deep-merge [& maps]
  (apply merge-with
    (fn [a b] (if (map? a) (deep-merge a b) b))
    maps))
```

## Efficient Map Iteration

`reduce-kv` avoids creating `MapEntry` objects and is more efficient than destructuring with `reduce` or `for` for map iteration.

```clojure
;; Iterate entries
(for [[k v] {:a 1 :b 2}]
  (str k "=" v))
; => (":a=1" ":b=2")

;; reduce-kv (more efficient)
(reduce-kv
  (fn [acc k v] (assoc acc k (inc v)))
  {}
  {:a 1 :b 2})
; => {:a 2 :b 3}
```

## Tree Navigation with Zippers

Zippers functionally navigate and edit trees; use `z/root` to retrieve the modified tree.

```clojure
(require '[clojure.zip :as z])

(def tree [1 [2 3] [4 [5 6]]])
(def loc (z/vector-zip tree))

;; Navigate
(-> loc z/down z/right z/down z/node) ; => 2

;; Edit
(-> loc
    z/down
    z/right
    (z/replace [:new])
    z/root)
; => [1 [:new] [4 [5 6]]]
```
