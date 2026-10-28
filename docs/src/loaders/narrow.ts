/**
 * Narrows a parsed value to a mapping.
 *
 * @param value - The value, as a parser gave it.
 * @param where - Where the value is, for the error.
 * @returns The value, as a mapping from each key to its value.
 * @throws An `Error` that names `where` when the value is not a mapping.
 */
export function recordOf(value: unknown, where: string): Record<string, unknown> {
	if (!isRecord(value)) {
		throw new Error(`${where} is not a mapping.`);
	}
	return value;
}

/**
 * Narrows a parsed value to a list.
 *
 * @param value - The value, as a parser gave it.
 * @param where - Where the value is, for the error.
 * @returns The value, as a list.
 * @throws An `Error` that names `where` when the value is not a list.
 */
export function arrayOf(value: unknown, where: string): readonly unknown[] {
	if (!Array.isArray(value)) {
		throw new Error(`${where} is not a list.`);
	}
	return value;
}

/**
 * Narrows a parsed value to a string.
 *
 * @param value - The value, as a parser gave it.
 * @param where - Where the value is, for the error.
 * @returns The value.
 * @throws An `Error` that names `where` when the value is not a string.
 */
export function stringOf(value: unknown, where: string): string {
	if (typeof value !== 'string') {
		throw new Error(`${where} is not a string.`);
	}
	return value;
}

/**
 * Tells whether a parsed value is a mapping, rather than a list or a scalar.
 *
 * @param value - The value, as a parser gave it.
 * @returns Whether the value is a mapping.
 */
export function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}
