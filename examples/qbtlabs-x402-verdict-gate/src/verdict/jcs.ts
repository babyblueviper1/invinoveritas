/**
 * RFC 8785 JSON Canonicalization Scheme (JCS), the subset needed to recompute invinoveritas hashes.
 *
 * invinoveritas hashes action arguments and the decision_ref preimage as sha256(JCS(value)). JCS is:
 * no whitespace, object keys sorted by UTF-16 code units, numbers in ECMAScript Number.prototype.toString
 * form, strings escaped the way JSON.stringify escapes them. That is exactly JavaScript's native JSON
 * behaviour once keys are sorted, so this stays small and dependency-free.
 */

export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };

export function canonicalize(value: unknown): string {
  if (value === null) return 'null';
  switch (typeof value) {
    case 'boolean':
      return value ? 'true' : 'false';
    case 'number':
      if (!Number.isFinite(value)) throw new Error('JCS: NaN and Infinity are not representable');
      return JSON.stringify(value);
    case 'string':
      return JSON.stringify(value);
    case 'bigint':
      throw new Error('JCS: bigint is not a JSON value; pass it as a decimal string');
    case 'object': {
      if (Array.isArray(value)) return '[' + value.map((v) => canonicalize(v)).join(',') + ']';
      const obj = value as Record<string, unknown>;
      const keys = Object.keys(obj).filter((k) => obj[k] !== undefined).sort();
      return '{' + keys.map((k) => JSON.stringify(k) + ':' + canonicalize(obj[k])).join(',') + '}';
    }
    default:
      throw new Error(`JCS: unsupported type ${typeof value}`);
  }
}
