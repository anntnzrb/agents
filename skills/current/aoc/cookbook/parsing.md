# Parsing Cookbook

AoC input recipes for structured, grid, grouped, or coordinate parsing.

## Extract all integers
Scattered text such as `"pos=<3,-5>, vel=<-2,1>"`:

```python
import re
nums = [int(x) for x in re.findall(r'-?\d+', line)]
# [3, -5, -2, 1]
```

`-?` handles negative numbers; works on most AoC inputs.

## Parse character grids
Dense 2D access:

```python
lines = input.strip().split('\n')
grid = [list(line) for line in lines]
value = grid[row][col]
```

Sparse/dict grid:

```python
grid = {}
for row, line in enumerate(lines):
    for col, char in enumerate(line):
        if char != '.':
            grid[(row, col)] = char

value = grid.get((row, col), '.')
```

Use sparse grids for infinite grids or grids mostly containing empty cells.

## Parse blank-line groups
Sections separated by blank lines:

```python
groups = input.strip().split('\n\n')
for group in groups:
    items = group.split('\n')
```

Common pattern: first section rules, second section data.

## Parse key-value pairs
Lines such as `"name: value"` or `"key=value"`:

```python
data = {}
for line in lines:
    key, value = line.split(': ')  # or '='
    data[key] = value
```

Cast `value` to `int` or parse it further when needed.

## Parse instructions/opcodes
Lines such as `"mov R1 42"` or `"jnz x -3"`:

```python
for line in lines:
    parts = line.split()
    op, args = parts[0], parts[1:]

    match op:
        case 'mov': ...
        case 'jnz': ...
```

Use regex for complex formats:

```python
re.match(r'(\w+) (\w+) (-?\d+)', line)
```

## Cardinal directions
Four-direction grid movement; `(row, col)` has row increasing downward:

```python
UP, DOWN = (-1, 0), (1, 0)
LEFT, RIGHT = (0, -1), (0, 1)
DIRS4 = [UP, DOWN, LEFT, RIGHT]

# Move:
new_row, new_col = row + dr, col + dc
```

## 8-directional movement

```python
DIRS8 = [(dr, dc)
         for dr in [-1, 0, 1]
         for dc in [-1, 0, 1]
         if (dr, dc) != (0, 0)]
```

## Directions from characters
For `^v<>` or `UDLR` input:

```python
DIR_MAP = {
    'U': (-1, 0), '^': (-1, 0),
    'D': (1, 0),  'v': (1, 0),
    'L': (0, -1), '<': (0, -1),
    'R': (0, 1),  '>': (0, 1),
}
dr, dc = DIR_MAP[char]
```

## Rotation
Tuple formulas:

```python
# 90° clockwise:     (row, col) → (col, -row)
# 90° counter-clock: (row, col) → (-col, row)
# 180°:              (row, col) → (-row, -col)
```

Complex-number alternative:

```python
pos = col + row * 1j
turn_right = pos * -1j
turn_left = pos * 1j
```

Complex numbers make rotation trivial.

## Hex grid
Cube coordinates satisfy `x + y + z = 0`; directions include `ne` and `sw`:

```python
HEX_DIRS = {
    'e':  (1, -1, 0),  'w':  (-1, 1, 0),
    'ne': (1, 0, -1),  'sw': (-1, 0, 1),
    'nw': (0, 1, -1),  'se': (0, -1, 1),
}

def hex_move(pos, direction):
    dx, dy, dz = HEX_DIRS[direction]
    return (pos[0]+dx, pos[1]+dy, pos[2]+dz)

def hex_distance(a, b):
    return (abs(a[0]-b[0]) + abs(a[1]-b[1]) + abs(a[2]-b[2])) // 2
```

## Bounds checking

```python
def in_bounds(row, col, grid):
    return 0 <= row < len(grid) and 0 <= col < len(grid[0])

def neighbors(row, col, grid):
    for dr, dc in DIRS4:
        nr, nc = row + dr, col + dc
        if in_bounds(nr, nc, grid):
            yield nr, nc
```

For sparse grids, use `grid.get((r,c), default)` instead.

## Toroidal wrapping

```python
row = row % height
col = col % width
```

## Padding with sentinels
Avoid bounds checking by padding edges:

```python
padded = [['#'] * (width + 2)]
for line in lines:
    padded.append(['#'] + list(line) + ['#'])
padded.append(['#'] * (width + 2))
```

Choose a sentinel absent from real data.
