# Modern Python: 3.13 to 3.14

## Free-Threaded Python (3.13+)

True CPU-bound parallelism with threads, without multiprocessing overhead. Enable at build time with `--disable-gil`; experimental in 3.13.

```python
# Build/install with: --disable-gil
# True parallelism for CPU-bound threads

import threading

# These now run in parallel on multiple cores
threads = [
    threading.Thread(target=cpu_intensive, args=(data,))
    for data in chunks
]
for t in threads:
    t.start()
for t in threads:
    t.join()
```

## Copy and Replace (3.13+)

Copy an object while changing fields, especially dataclasses. `replace()` supports objects with `__replace__()`, including dataclasses, namedtuples, and custom classes.

```python
from copy import replace
from dataclasses import dataclass

@dataclass
class User:
    name: str
    age: int

alice = User("Alice", 30)
bob = replace(alice, name="Bob")
# User(name='Bob', age=30)
```

## Deprecated Decorator (3.13+)

`warnings.deprecated` marks APIs with proper warnings and clarifies migration paths.

```python
from warnings import deprecated

@deprecated("Use new_function() instead")
def old_function():
    ...

old_function()  # Emits DeprecationWarning
```

## Template Strings (3.14+)

`t"..."` creates safe, inspectable template objects rather than immediately evaluated f-string-like values; inspect or transform them before rendering. This helps prevent injection attacks in user-provided templates.

```python
name = "Alice"
age = 30

# Template object (not evaluated string)
template = t"Hello {name}, age {age}"

# Safer than f-strings for user templates
# Can inspect/transform before rendering
print(template.strings)       # ("Hello ", ", age ", "")
print(template.interpolations) # (Interpolation(name, ...), ...)
```

## Deferred Annotation Evaluation (3.14+)

Annotations evaluate lazily, enabling unquoted forward references to classes before full definition.

```python
# Forward references work without quotes!
class Node:
    def __init__(self, value: int):
        self.value = value
        self.next: Node | None = None  # No "Node" quotes needed

    def append(self, node: Node) -> Node:
        self.next = node
        return node
```

## Time-Sortable UUIDs (3.14+)

`uuid7()` includes a timestamp, producing chronologically sortable UUIDs that are more database-friendly than UUID v4 and suitable for database primary keys.

```python
from uuid import uuid7

id1 = uuid7()
id2 = uuid7()

assert id1 < id2  # Chronologically sortable!
# Great for database primary keys
```

## Pathlib Copy and Move (3.14+)

`Path` copy/move methods integrate file operations into pathlib, avoiding separate `shutil` imports.

```python
from pathlib import Path

src = Path("file.txt")
src.copy(Path("backup/file.txt"))
src.move(Path("archive/file.txt"))

# Directory copy
Path("src/").copy(Path("backup/"), recursive=True)
```

## Simplified Exception Syntax (3.14+)

Catch multiple exception types with comma-separated syntax, without tuple syntax; this reduces visual clutter and matches other Python syntax.

```python
# Multiple exception types without parentheses
try:
    risky_operation()
except ValueError, TypeError, KeyError:  # No tuple needed!
    handle_error()
```
