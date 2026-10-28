import { arrayOf, isRecord, recordOf, stringOf } from './narrow';

/**
 * Describes the values a JSON Schema accepts, in words a table cell can hold, such as `array of
 * string` or `"log", "discard" or "inherit"`. It knows the forms the contract's schemas use, and a
 * reference to a definition reads as the definition's title, or as the definition itself without
 * one.
 *
 * @param schema - The schema to describe.
 * @param definitions - The `$defs` of the document that holds the schema, which its references name.
 * @param where - Where the schema is, for errors.
 * @returns The description.
 * @throws An `Error` that names `where` when the schema takes a form the function doesn't know, so
 *   a new form fails the build rather than reading wrong.
 */
export function schemaText(
	schema: unknown,
	definitions: Readonly<Record<string, unknown>>,
	where: string
): string {
	const fields = recordOf(schema, where);
	if (fields.$ref !== undefined) {
		const name = stringOf(fields.$ref, `${where} $ref`).replace(/^#\/\$defs\//, '');
		const target = recordOf(definitions[name], `${where}'s $ref, ${name},`);
		return typeof target.title === 'string'
			? target.title
			: schemaText(target, definitions, `$defs/${name}`);
	}
	if ('const' in fields) {
		return JSON.stringify(fields.const);
	}
	if (fields.enum !== undefined) {
		return alternatives(
			arrayOf(fields.enum, `${where} enum`).map((value) => JSON.stringify(value))
		);
	}
	const choices = fields.anyOf ?? fields.oneOf;
	if (choices !== undefined) {
		return alternatives(
			arrayOf(choices, `${where} anyOf`).map((choice, index) =>
				schemaText(choice, definitions, `${where} choice ${String(index + 1)}`)
			)
		);
	}
	if (Array.isArray(fields.type)) {
		return alternatives(
			fields.type.map((type) => typeText({ ...fields, type }, definitions, where))
		);
	}
	return typeText(fields, definitions, where);
}

// One JSON type, with the constraints a reader of the table needs.
function typeText(
	fields: Readonly<Record<string, unknown>>,
	definitions: Readonly<Record<string, unknown>>,
	where: string
): string {
	const type = stringOf(fields.type, `${where} type`);
	switch (type) {
		case 'string': {
			const pattern = typeof fields.pattern === 'string' ? ` matching ${fields.pattern}` : '';
			const length =
				typeof fields.maxLength === 'number'
					? `, at most ${String(fields.maxLength)} characters`
					: '';
			return `string${pattern}${length}`;
		}
		case 'integer':
		case 'number':
			if (typeof fields.minimum === 'number') {
				return `${type} of at least ${String(fields.minimum)}`;
			}
			if (typeof fields.exclusiveMinimum === 'number') {
				return `${type} greater than ${String(fields.exclusiveMinimum)}`;
			}
			return type;
		case 'boolean':
		case 'null':
			return type;
		case 'array':
			return `array of ${schemaText(fields.items, definitions, `${where} items`)}`;
		case 'object':
			return isRecord(fields.additionalProperties)
				? `map of string to ${schemaText(fields.additionalProperties, definitions, `${where} additionalProperties`)}`
				: 'object';
		default:
			throw new Error(`${where} has the type ${type}, which the site can't describe.`);
	}
}

function alternatives(texts: readonly string[]): string {
	const last = texts.at(-1);
	return texts.length < 2 || last === undefined
		? texts.join('')
		: `${texts.slice(0, -1).join(', ')} or ${last}`;
}
