# Type System

This document describes the port type system used in LiGuard-Web for validating connections between nodes.

## Overview

Every port (input or output) on a node has a type. The type system enforces that connections are only made between compatible types, preventing runtime errors.

## Type Descriptors

Types are represented as `TypeDescriptor` objects:

```typescript
interface TypeDescriptor {
  kind: string;           // The base type kind
  item?: TypeDescriptor;  // Element type for lists, options
  value?: TypeDescriptor; // Value type for maps
  fields?: Record<string, TypeDescriptor>; // Fields for records
  nullable?: boolean;     // Whether null is allowed
  metadata?: Record<string, any>; // Additional type info (e.g., tensor dtype)
}
```

## Base Types

| Kind | Description | Example Values |
|------|-------------|----------------|
| `any` | Accepts any type | - |
| `unknown` | Unknown type (compatible with any) | - |
| `int` | Integer number | `42`, `-5`, `0` |
| `float` | Floating-point number | `3.14`, `-0.5` |
| `string` | Text | `"hello"`, `""` |
| `bool` | Boolean | `true`, `false` |
| `control` | Control flow signal | - |

## Container Types

### List

Ordered collection of elements:

```typescript
{ kind: "list", item: { kind: "int" } }  // list<int>
```

Label: `list<int>`

### Map

Key-value mapping (keys are always strings):

```typescript
{ kind: "map", value: { kind: "string" } }  // map<string>
```

Label: `map<string>`

### Option

Optional value (may be null):

```typescript
{ kind: "option", item: { kind: "int" } }  // int?
```

Label: `int?`

### Record

Structured object with named fields:

```typescript
{
  kind: "record",
  fields: {
    name: { kind: "string" },
    age: { kind: "int" }
  }
}
```

Label: `record`

## Special Types

### Tensor

Multi-dimensional array with optional dtype:

```typescript
{ kind: "tensor" }                              // tensor (any dtype)
{ kind: "tensor", metadata: { dtype: "float32" } }  // tensor<float32>
```

### Image

Image data:

```typescript
{ kind: "image" }
```

### DataFrame

Tabular data:

```typescript
{ kind: "dataframe" }
```

## Type Compatibility Rules

The function `areTypesCompatible(source, target)` determines if a connection is valid.

### Rule 1: Any Type

`any` and `unknown` are compatible with everything:

```
any     -> int      ✓
string  -> any      ✓
unknown -> list     ✓
```

### Rule 2: Same Type

Same types are always compatible:

```
int    -> int     ✓
string -> string  ✓
bool   -> bool    ✓
```

### Rule 3: Numeric Promotion

`int` can be assigned to `float` (implicit promotion):

```
int   -> float  ✓
float -> int    ✗  (precision loss)
```

### Rule 4: Nullable Safety

Non-nullable can flow to nullable, but not vice versa:

```
string   -> string?  ✓
string?  -> string   ✗  (might be null)
```

### Rule 5: Container Element Compatibility

Container types check element compatibility recursively:

```
list<int>    -> list<float>   ✓  (int promotes to float)
list<float>  -> list<int>     ✗
list<int>    -> list<string>  ✗

map<int>     -> map<float>    ✓
map<string>  -> map<int>      ✗
```

### Rule 6: Record Structural Subtyping

Source record must have all fields required by target:

```typescript
// Source
{ name: string, age: int, email: string }

// Target (subset)
{ name: string }

// Result: ✓ (source has all target fields)
```

```typescript
// Source
{ name: string }

// Target (has extra field)
{ name: string, age: int }

// Result: ✗ (source missing 'age')
```

### Rule 7: Tensor Dtype Compatibility

Tensors with unspecified dtype accept any tensor:

```
tensor<float32>  -> tensor           ✓
tensor           -> tensor<float32>  ✓
tensor<float32>  -> tensor<float64>  ✗  (dtype mismatch)
```

## Type Normalization

Before comparison, types are normalized:

### String to TypeDescriptor

```typescript
normalizeType("int")      // { kind: "int" }
normalizeType("string")   // { kind: "string" }
```

### Number Alias

```typescript
normalizeType("number")   // { kind: "float" }
```

### Legacy elementType

```typescript
// Old format
{ kind: "list", elementType: "int" }

// Normalized to
{ kind: "list", item: { kind: "int" } }
```

### Null/Undefined

```typescript
normalizeType(null)       // { kind: "any" }
normalizeType(undefined)  // { kind: "any" }
```

## Type Labels

The `getTypeLabel()` function generates human-readable type strings:

| TypeDescriptor | Label |
|---------------|-------|
| `{ kind: "int" }` | `int` |
| `{ kind: "list", item: { kind: "int" } }` | `list<int>` |
| `{ kind: "map", value: { kind: "string" } }` | `map<string>` |
| `{ kind: "option", item: { kind: "int" } }` | `int?` |
| `{ kind: "string", nullable: true }` | `string?` |
| `{ kind: "tensor", metadata: { dtype: "float32" } }` | `tensor<float32>` |
| `{ kind: "list", item: { kind: "list", item: { kind: "int" } } }` | `list<list<int>>` |

## Type Predicates

Helper functions for checking type categories:

```typescript
isAnyType("any")        // true
isAnyType("unknown")    // true
isAnyType("int")        // false

isNumericType("int")    // true
isNumericType("float")  // true
isNumericType("number") // true
isNumericType("string") // false

isContainerType("list")   // true
isContainerType("map")    // true
isContainerType("option") // true
isContainerType("record") // true
isContainerType("int")    // false

isControlType("control")  // true
isControlType("int")      // false
```

## Usage in Node Definitions

When defining a node, specify port types:

```python
NodeSpec(
    id="add",
    type="Math.Add",
    inputs=[
        PortSpec(name="a", type={"kind": "float"}),
        PortSpec(name="b", type={"kind": "float"}),
    ],
    outputs=[
        PortSpec(name="result", type={"kind": "float"}),
    ]
)
```

## Frontend Validation

The frontend validates connections before allowing them:

```typescript
const isValidConnection = useCallback((connection) => {
  const sourceType = getPortType(connection.source, connection.sourceHandle);
  const targetType = getPortType(connection.target, connection.targetHandle);

  return areTypesCompatible(sourceType, targetType);
}, [getPortType]);
```

## See Also

- [Architecture Overview](./overview.md)
- [Execution Engine](./execution-engine.md)
- [Node Authoring Guide](../nodes/authoring-guide.md)
