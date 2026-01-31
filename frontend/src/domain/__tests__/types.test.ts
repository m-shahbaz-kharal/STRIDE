/**
 * Tests for domain type system.
 *
 * @jest-environment jsdom
 */

import { describe, it, expect } from 'vitest';
import {
  normalizeType,
  areTypesCompatible,
  getTypeLabel,
  isAnyType,
  isNumericType,
  isContainerType,
  isControlType,
  TypeDescriptor,
} from '../types';

describe('normalizeType', () => {
  it('should return any type for undefined input', () => {
    const result = normalizeType(undefined);
    expect(result.kind).toBe('any');
  });

  it('should return any type for null input', () => {
    const result = normalizeType(null);
    expect(result.kind).toBe('any');
  });

  it('should create simple type from string', () => {
    const result = normalizeType('int');
    expect(result.kind).toBe('int');
    expect(result.item).toBeUndefined();
  });

  it('should normalize "number" to "float"', () => {
    const result = normalizeType('number');
    expect(result.kind).toBe('float');
  });

  it('should preserve existing TypeDescriptor fields', () => {
    const input: TypeDescriptor = { kind: 'list', item: { kind: 'string' } };
    const result = normalizeType(input);
    expect(result.kind).toBe('list');
    expect(result.item?.kind).toBe('string');
  });

  it('should normalize elementType to item for lists', () => {
    const input = { kind: 'list', elementType: 'int' } as unknown as TypeDescriptor;
    const result = normalizeType(input);
    expect(result.item?.kind).toBe('int');
  });

  it('should normalize elementType to value for maps', () => {
    const input = { kind: 'map', elementType: 'string' } as unknown as TypeDescriptor;
    const result = normalizeType(input);
    expect(result.value?.kind).toBe('string');
  });

  it('should recursively normalize nested item types', () => {
    const input: TypeDescriptor = {
      kind: 'list',
      item: { kind: 'list', item: { kind: 'int' } },
    };
    const result = normalizeType(input);
    expect(result.item?.item?.kind).toBe('int');
  });

  it('should recursively normalize record fields', () => {
    const input: TypeDescriptor = {
      kind: 'record',
      fields: {
        name: { kind: 'string' },
        count: { kind: 'number' } as TypeDescriptor, // Will be normalized to float
      },
    };
    const result = normalizeType(input);
    expect(result.fields?.name.kind).toBe('string');
    // Note: number normalization happens at string level, not in nested objects
    expect(result.fields?.count.kind).toBe('number');
  });
});

describe('areTypesCompatible', () => {
  it('should return true when target is any', () => {
    expect(areTypesCompatible('int', 'any')).toBe(true);
    expect(areTypesCompatible('string', 'any')).toBe(true);
    expect(areTypesCompatible({ kind: 'list', item: { kind: 'int' } }, 'any')).toBe(true);
  });

  it('should return true when source is any', () => {
    expect(areTypesCompatible('any', 'int')).toBe(true);
    expect(areTypesCompatible('any', 'string')).toBe(true);
  });

  it('should return true when target is unknown', () => {
    expect(areTypesCompatible('int', 'unknown')).toBe(true);
  });

  it('should allow int to float promotion', () => {
    expect(areTypesCompatible('int', 'float')).toBe(true);
  });

  it('should not allow float to int', () => {
    expect(areTypesCompatible('float', 'int')).toBe(false);
  });

  it('should return true for same types', () => {
    expect(areTypesCompatible('string', 'string')).toBe(true);
    expect(areTypesCompatible('int', 'int')).toBe(true);
    expect(areTypesCompatible('bool', 'bool')).toBe(true);
    expect(areTypesCompatible('control', 'control')).toBe(true);
  });

  it('should return false for different types', () => {
    expect(areTypesCompatible('string', 'int')).toBe(false);
    expect(areTypesCompatible('bool', 'string')).toBe(false);
    expect(areTypesCompatible('list', 'map')).toBe(false);
  });

  it('should enforce nullable safety', () => {
    const nullable: TypeDescriptor = { kind: 'string', nullable: true };
    const nonNullable: TypeDescriptor = { kind: 'string', nullable: false };

    expect(areTypesCompatible(nullable, nonNullable)).toBe(false);
    expect(areTypesCompatible(nullable, nullable)).toBe(true);
    expect(areTypesCompatible(nonNullable, nullable)).toBe(true);
  });

  it('should check list element compatibility', () => {
    const listInt: TypeDescriptor = { kind: 'list', item: { kind: 'int' } };
    const listFloat: TypeDescriptor = { kind: 'list', item: { kind: 'float' } };
    const listString: TypeDescriptor = { kind: 'list', item: { kind: 'string' } };

    expect(areTypesCompatible(listInt, listFloat)).toBe(true); // int promotion
    expect(areTypesCompatible(listFloat, listInt)).toBe(false);
    expect(areTypesCompatible(listInt, listString)).toBe(false);
  });

  it('should check map value compatibility', () => {
    const mapInt: TypeDescriptor = { kind: 'map', value: { kind: 'int' } };
    const mapFloat: TypeDescriptor = { kind: 'map', value: { kind: 'float' } };

    expect(areTypesCompatible(mapInt, mapFloat)).toBe(true);
    expect(areTypesCompatible(mapFloat, mapInt)).toBe(false);
  });

  it('should check option element compatibility', () => {
    const optionInt: TypeDescriptor = { kind: 'option', item: { kind: 'int' } };
    const optionFloat: TypeDescriptor = { kind: 'option', item: { kind: 'float' } };

    expect(areTypesCompatible(optionInt, optionFloat)).toBe(true);
    expect(areTypesCompatible(optionFloat, optionInt)).toBe(false);
  });

  it('should check record field compatibility', () => {
    const source: TypeDescriptor = {
      kind: 'record',
      fields: {
        name: { kind: 'string' },
        age: { kind: 'int' },
      },
    };
    const targetSubset: TypeDescriptor = {
      kind: 'record',
      fields: {
        name: { kind: 'string' },
      },
    };
    const targetExtra: TypeDescriptor = {
      kind: 'record',
      fields: {
        name: { kind: 'string' },
        email: { kind: 'string' },
      },
    };

    expect(areTypesCompatible(source, targetSubset)).toBe(true);
    expect(areTypesCompatible(source, targetExtra)).toBe(false);
  });

  it('should check tensor dtype compatibility', () => {
    const f32: TypeDescriptor = { kind: 'tensor', metadata: { dtype: 'float32' } };
    const f64: TypeDescriptor = { kind: 'tensor', metadata: { dtype: 'float64' } };
    const tensorAny: TypeDescriptor = { kind: 'tensor' };

    expect(areTypesCompatible(f32, f64)).toBe(false);
    expect(areTypesCompatible(f32, tensorAny)).toBe(true);
    expect(areTypesCompatible(tensorAny, f32)).toBe(true);
  });
});

describe('getTypeLabel', () => {
  it('should return kind for simple types', () => {
    expect(getTypeLabel('int')).toBe('int');
    expect(getTypeLabel('string')).toBe('string');
    expect(getTypeLabel('bool')).toBe('bool');
  });

  it('should format list types', () => {
    expect(getTypeLabel({ kind: 'list', item: { kind: 'int' } })).toBe('list<int>');
    expect(getTypeLabel({ kind: 'list', item: { kind: 'string' } })).toBe('list<string>');
  });

  it('should format nested list types', () => {
    const nested: TypeDescriptor = {
      kind: 'list',
      item: { kind: 'list', item: { kind: 'int' } },
    };
    expect(getTypeLabel(nested)).toBe('list<list<int>>');
  });

  it('should format map types', () => {
    expect(getTypeLabel({ kind: 'map', value: { kind: 'string' } })).toBe('map<string>');
    expect(getTypeLabel({ kind: 'map' })).toBe('map');
  });

  it('should format option types', () => {
    expect(getTypeLabel({ kind: 'option', item: { kind: 'int' } })).toBe('int?');
  });

  it('should format nullable types', () => {
    expect(getTypeLabel({ kind: 'string', nullable: true })).toBe('string?');
  });

  it('should format tensor types with dtype', () => {
    expect(getTypeLabel({ kind: 'tensor', metadata: { dtype: 'float32' } })).toBe('tensor<float32>');
    expect(getTypeLabel({ kind: 'tensor' })).toBe('tensor');
  });
});

describe('type predicates', () => {
  it('isAnyType should identify any and unknown', () => {
    expect(isAnyType('any')).toBe(true);
    expect(isAnyType('unknown')).toBe(true);
    expect(isAnyType({ kind: 'any' })).toBe(true);
    expect(isAnyType('int')).toBe(false);
  });

  it('isNumericType should identify numeric types', () => {
    expect(isNumericType('int')).toBe(true);
    expect(isNumericType('float')).toBe(true);
    expect(isNumericType('number')).toBe(true);
    expect(isNumericType('string')).toBe(false);
  });

  it('isContainerType should identify container types', () => {
    expect(isContainerType('list')).toBe(true);
    expect(isContainerType('map')).toBe(true);
    expect(isContainerType('option')).toBe(true);
    expect(isContainerType('record')).toBe(true);
    expect(isContainerType('int')).toBe(false);
  });

  it('isControlType should identify control type', () => {
    expect(isControlType('control')).toBe(true);
    expect(isControlType({ kind: 'control' })).toBe(true);
    expect(isControlType('int')).toBe(false);
  });
});
