# Functional Patterns: Iterators

Iterator algebra, batching, filtering, grouping, and itertools recipes.

## Infinite Iterators

Generate infinite sequences or repeated values.

```python
from itertools import count, cycle, repeat

# count: Infinite counter
counter = count(start=10, step=2)
assert next(counter) == 10
assert next(counter) == 12

# cycle: Endlessly repeat iterable
colors = cycle(['red', 'green', 'blue'])
assert next(colors) == 'red'

# repeat: Repeat value n times
repeated = list(repeat('x', 3))
assert repeated == ['x', 'x', 'x']
```

Memory-efficient, but require explicit stopping conditions; limit with `islice()` or `takewhile()`.

## Chaining and Accumulating

Concatenate iterables and compute running aggregations.

```python
from itertools import chain, accumulate
from operator import add, mul

# chain: Concatenate iterables
combined = list(chain([1, 2], [3, 4], [5, 6]))
assert combined == [1, 2, 3, 4, 5, 6]

# accumulate: Running total/aggregation
cumsum = list(accumulate([1, 2, 3, 4], add))
assert cumsum == [1, 3, 6, 10]

cumprod = list(accumulate([1, 2, 3, 4], mul))
assert cumprod == [1, 2, 6, 24]
```

`chain.from_iterable()` efficiently flattens nested iterables; `accumulate()` supports running totals and cumulative operations.

## Batching and Pairing

Group elements into chunks or consecutive pairs.

```python
from itertools import batched, pairwise

# batched: Group into fixed-size chunks (3.12+)
data = list(batched('ABCDEFG', 2))
assert data == [('A', 'B'), ('C', 'D'), ('E', 'F'), ('G',)]

# pairwise: Consecutive overlapping pairs
pairs = list(pairwise('ABCD'))
assert pairs == [('A', 'B'), ('B', 'C'), ('C', 'D')]
```

`batched()` suits chunk processing; `pairwise()` suits consecutive comparisons or differences.

## Filtering Iterators

Filter or slice iterators by conditions.

```python
from itertools import filterfalse, takewhile, dropwhile, islice

numbers = [1, 4, 6, 3, 8, 2, 5]

# filterfalse: Opposite of filter
odds = list(filterfalse(lambda x: x % 2 == 0, numbers))
assert odds == [1, 3, 5]

# takewhile: Keep while condition is true
taken = list(takewhile(lambda x: x < 5, [1, 4, 6, 3, 8]))
assert taken == [1, 4]  # Stops at 6

# dropwhile: Skip while condition is true
dropped = list(dropwhile(lambda x: x < 5, [1, 4, 6, 3, 8]))
assert dropped == [6, 3, 8]

# islice: Slice without creating list
sliced = list(islice(range(10), 2, 7, 2))
assert sliced == [2, 4, 6]
```

`takewhile()` and `dropwhile()` stop at the first failure, unlike `filter()`; `islice()` enables memory-efficient slicing of large iterators.

## Combinatorics

Generate combinations, permutations, or Cartesian products.

```python
from itertools import combinations, permutations, product

# combinations: All r-length subsets
combos = list(combinations('ABC', 2))
assert combos == [('A', 'B'), ('A', 'C'), ('B', 'C')]

# permutations: All orderings
perms = list(permutations('ABC', 2))
assert len(perms) == 6  # 3 * 2

# product: Cartesian product (like nested loops)
pairs = list(product('AB', [1, 2]))
assert pairs == [('A', 1), ('A', 2), ('B', 1), ('B', 2)]

# product with repeat
all_binary = list(product([0, 1], repeat=3))
assert len(all_binary) == 8  # 2^3
```

These functions grow exponentially: use small sets or `islice()` to limit output.

## Grouping Elements

Group consecutive equal elements or group by a key.

```python
from itertools import groupby

# groupby: Group consecutive equal elements
data = 'AAAABBBCCDAA'
grouped = [(key, len(list(group))) for key, group in groupby(data)]
assert grouped == [('A', 4), ('B', 3), ('C', 2), ('D', 1), ('A', 2)]

# groupby requires sorted data for meaningful grouping
people = [
    {"name": "Alice", "dept": "eng"},
    {"name": "Bob", "dept": "eng"},
    {"name": "Carol", "dept": "hr"},
]
sorted_people = sorted(people, key=lambda x: x["dept"])

for dept, group in groupby(sorted_people, key=lambda x: x["dept"]):
    members = [p["name"] for p in group]
    print(f"{dept}: {members}")
```

Sort by the grouping key first: `groupby()` groups consecutive, not global, matches.

## Itertools Recipes

Common patterns—flattening, taking `n` items, and ordered uniqueness—are often more efficient than list-based approaches.

```python
from itertools import islice, chain

# flatten one level
def flatten(list_of_lists):
    return chain.from_iterable(list_of_lists)

nested = [[1, 2], [3, 4], [5, 6]]
assert list(flatten(nested)) == [1, 2, 3, 4, 5, 6]

# take first n items
def take(n: int, iterable):
    return list(islice(iterable, n))

assert take(3, range(10)) == [0, 1, 2]

# unique elements (preserving order)
def unique(iterable, key=None):
    seen = set()
    for item in iterable:
        k = key(item) if key else item
        if k not in seen:
            seen.add(k)
            yield item
```

