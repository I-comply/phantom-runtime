// Minimal JSON Schema (draft-07 subset) validator: type, enum, const, required, properties,
// additionalProperties, items, minItems, maxItems, minLength, pattern. Zero dependencies.
export function validate(schema, value, path = "$") {
  const errs = [];
  const types = schema.type ? [].concat(schema.type) : null;
  const t = value === null ? "null" : Array.isArray(value) ? "array" : typeof value === "number" && Number.isInteger(value) ? "integer" : typeof value;
  if (types) {
    const ok = types.some((x) => x === t || (x === "number" && (t === "integer" || t === "number")));
    if (!ok) return [`${path}: expected ${types.join("|")}, got ${t}`];
  }
  if (schema.enum && !schema.enum.includes(value)) errs.push(`${path}: ${JSON.stringify(value)} not in enum [${schema.enum.join(", ")}]`);
  if ("const" in schema && value !== schema.const) errs.push(`${path}: expected const ${JSON.stringify(schema.const)}`);
  if (typeof value === "string") {
    if (schema.minLength != null && value.length < schema.minLength) errs.push(`${path}: shorter than ${schema.minLength}`);
    if (schema.pattern && !new RegExp(schema.pattern).test(value)) errs.push(`${path}: does not match ${schema.pattern}`);
  }
  if (Array.isArray(value)) {
    if (schema.minItems != null && value.length < schema.minItems) errs.push(`${path}: fewer than ${schema.minItems} items`);
    if (schema.maxItems != null && value.length > schema.maxItems) errs.push(`${path}: more than ${schema.maxItems} items`);
    if (schema.items) value.forEach((v, i) => errs.push(...validate(schema.items, v, `${path}[${i}]`)));
  }
  if (t === "object") {
    for (const r of schema.required || []) if (!(r in value)) errs.push(`${path}: missing required "${r}"`);
    const props = schema.properties || {};
    for (const [k, v] of Object.entries(value)) {
      if (k in props) errs.push(...validate(props[k], v, `${path}.${k}`));
      else if (schema.additionalProperties === false) errs.push(`${path}: unexpected property "${k}"`);
    }
  }
  return errs;
}
