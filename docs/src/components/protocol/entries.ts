/**
 * Sorts a collection's entries by ID, so a table lists them in the same order on every platform:
 * Astro returns a collection's entries in no fixed order.
 *
 * @param entries - A collection's entries, as `getCollection()` returns them.
 * @returns A sorted copy.
 */
export function sortedById<Entry extends { readonly id: string }>(
	entries: readonly Entry[]
): Entry[] {
	return entries.toSorted((a, b) => a.id.localeCompare(b.id, 'en'));
}
