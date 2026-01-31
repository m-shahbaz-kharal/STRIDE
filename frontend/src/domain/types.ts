/**
 * Type system domain model.
 *
 * Provides type descriptors and compatibility rules for port types.
 * This is the source of truth for type compatibility logic, extracted
 * from useConnectionValidation for better testability and reuse.
 */

/**
 * Describes the type of a port value.
 *
 * This is the canonical representation of port types used for
 * validation and compatibility checking.
 */
export interface TypeDescriptor {
  kind: string;
  item?: TypeDescriptor;
  value?: TypeDescriptor;
  key?: TypeDescriptor;
  fields?: Record<string, TypeDescriptor>;
  nullable?: boolean;
  metadata?: Record<string, unknown>;
}

/**
 * Normalize a type specification to a TypeDescriptor.
 *
 * This handles various input formats:
 * - undefined/null -> { kind: 'any' }
 * - 'int' -> { kind: 'int' }
 * - 'number' -> { kind: 'float' }  // Normalize number to float
 * - { kind: 'list', item: 'int' } -> { kind: 'list', item: { kind: 'int' } }
 *
 * @param type - The type specification in any supported format
 * @returns A normalized TypeDescriptor
 */
export function normalizeType(type?: TypeDescriptor | string | null): TypeDescriptor {
  if (!type) {
    return { kind: 'any' };
  }

  if (typeof type === 'string') {
    // Normalize common type aliases
    if (type === 'number') {
      return { kind: 'float' };
    }
    return { kind: type };
  }

  // Already a TypeDescriptor, normalize nested types
  const normalized: TypeDescriptor = { ...type };

  // Handle elementType -> item normalization (backend uses both)
  const elementType =
    (normalized as unknown as Record<string, unknown>).elementType ??
    (normalized as unknown as Record<string, unknown>).element_type;

  if (elementType && !normalized.item) {
    const normalizedElement = normalizeType(elementType as TypeDescriptor | string);

    if (normalized.kind === 'map') {
      // For maps, elementType often means value type
      if (!normalized.value) {
        normalized.value = normalizedElement;
      }
    } else {
      normalized.item = normalizedElement;
    }
  }

  // Recursively normalize nested types
  if (normalized.item && typeof normalized.item === 'object') {
    normalized.item = normalizeType(normalized.item);
  }

  if (normalized.value && typeof normalized.value === 'object') {
    normalized.value = normalizeType(normalized.value);
  }

  if (normalized.fields) {
    normalized.fields = Object.fromEntries(
      Object.entries(normalized.fields).map(([key, value]) => [key, normalizeType(value)])
    );
  }

  return normalized;
}

/**
 * Check if a source type is compatible with a target type.
 *
 * Compatibility rules:
 * 1. 'any' or 'unknown' types are compatible with anything
 * 2. int is compatible with float (numeric promotion)
 * 3. Nullable source requires nullable target (nullable safety)
 * 4. Container types check element type compatibility recursively
 * 5. Record types check that all target fields exist with compatible types
 *
 * @param sourceType - The type of the source port (output)
 * @param targetType - The type of the target port (input)
 * @returns True if the connection is valid
 */
export function areTypesCompatible(
  sourceType: TypeDescriptor | string | undefined,
  targetType: TypeDescriptor | string | undefined
): boolean {
  const src = normalizeType(sourceType);
  const tgt = normalizeType(targetType);

  // Rule 1: Any/unknown accepts or provides anything
  if (tgt.kind === 'any' || src.kind === 'any') {
    return true;
  }
  if (tgt.kind === 'unknown' || src.kind === 'unknown') {
    return true;
  }

  // Rule 2: int -> float promotion
  if (src.kind === 'int' && tgt.kind === 'float') {
    return true;
  }

  // Rule 3: Nullable safety (source can be null, target must accept null)
  if (src.nullable && !tgt.nullable) {
    return false;
  }

  // Kind must match for remaining checks
  if (src.kind !== tgt.kind) {
    return false;
  }

  // Rule 4: Container element type compatibility
  if (src.kind === 'list' && src.item && tgt.item) {
    return areTypesCompatible(src.item, tgt.item);
  }

  if (src.kind === 'map' && src.value && tgt.value) {
    return areTypesCompatible(src.value, tgt.value);
  }

  if (src.kind === 'option' && src.item && tgt.item) {
    return areTypesCompatible(src.item, tgt.item);
  }

  // Rule 5: Record field compatibility
  if (src.kind === 'record' && src.fields && tgt.fields) {
    const tgtKeys = Object.keys(tgt.fields);
    return tgtKeys.every(
      (key) =>
        src.fields &&
        src.fields[key] &&
        areTypesCompatible(src.fields[key], tgt.fields![key])
    );
  }

  // Tensor dtype compatibility
  if (src.kind === 'tensor') {
    const srcDtype = src.metadata?.dtype;
    const tgtDtype = tgt.metadata?.dtype;
    if (srcDtype && tgtDtype && srcDtype !== tgtDtype) {
      return false;
    }
  }

  return true;
}

/**
 * Get a human-readable label for a type.
 *
 * @param typeDesc - The type to describe
 * @returns A human-readable string like "list<int>" or "map<string>"
 */
export function getTypeLabel(typeDesc: TypeDescriptor | string | undefined): string {
  const td = normalizeType(typeDesc);

  if (td.kind === 'list' && td.item) {
    return `list<${getTypeLabel(td.item)}>`;
  }

  if (td.kind === 'map') {
    if (td.value) {
      return `map<${getTypeLabel(td.value)}>`;
    }
    return 'map';
  }

  if (td.kind === 'option' && td.item) {
    return `${getTypeLabel(td.item)}?`;
  }

  if (td.kind === 'record' && td.fields) {
    const fieldStrs = Object.entries(td.fields).map(
      ([name, ft]) => `${name}: ${getTypeLabel(ft)}`
    );
    return `{${fieldStrs.join(', ')}}`;
  }

  if (td.kind === 'tensor' && td.metadata?.dtype) {
    return `tensor<${td.metadata.dtype}>`;
  }

  if (td.nullable && td.kind !== 'any' && td.kind !== 'unknown') {
    return `${td.kind}?`;
  }

  return td.kind;
}

/**
 * Check if a type is the 'any' type that accepts anything.
 */
export function isAnyType(typeDesc: TypeDescriptor | string | undefined): boolean {
  const td = normalizeType(typeDesc);
  return td.kind === 'any' || td.kind === 'unknown';
}

/**
 * Check if a type is a numeric type.
 */
export function isNumericType(typeDesc: TypeDescriptor | string | undefined): boolean {
  const td = normalizeType(typeDesc);
  return td.kind === 'int' || td.kind === 'float' || td.kind === 'number';
}

/**
 * Check if a type is a container type.
 */
export function isContainerType(typeDesc: TypeDescriptor | string | undefined): boolean {
  const td = normalizeType(typeDesc);
  return td.kind === 'list' || td.kind === 'map' || td.kind === 'option' || td.kind === 'record';
}

/**
 * Check if a type is a control flow type.
 */
export function isControlType(typeDesc: TypeDescriptor | string | undefined): boolean {
  const td = normalizeType(typeDesc);
  return td.kind === 'control';
}
