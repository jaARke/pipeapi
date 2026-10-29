import { readFileSync } from 'node:fs';
import { file, type Loader } from 'astro/loaders';
import { z } from 'astro/zod';
import { parse } from 'yaml';
import {
	conformanceCasesFilePath,
	conformanceCasesSchemaPath,
	conformanceComponentsFilePath,
} from '../conformance';
import { repositoryFileUrl } from '../protocol';
import { isRecord, recordOf } from './narrow';

// One case as the site shows it, with the defaults its schema gives the fields it leaves out. A
// left-out transports or platforms means every one, a left-out vias that the case doesn't vary by
// them, and a left-out relies_on none. The kinds and backends are the ones the site knows how to
// describe, so a new one fails the build until it does.
const conformanceCase = z.object({
	id: z.string(),
	title: z.string(),
	expectation: z.string(),
	kind: z.enum(['server', 'connector']),
	backends: z.array(z.enum(['app', 'fake'])),
	needs: z.array(z.string()),
	transports: z.array(z.string()).optional(),
	platforms: z.array(z.string()).optional(),
	vias: z.array(z.string()).optional(),
	once: z.boolean(),
	relies_on: z.array(z.string()).optional(),
	baseline: z.boolean(),
	slow: z.boolean(),
	covers: z.array(z.string()),
});

// The case list as the site shows it: the areas in the file's order, each with its cases, the
// invariants, each with the defaults its schema gives the fields it leaves out, and the anchors no
// case covers with the reason. It is the site's own view of the file, which `just lint` validates
// against its schema.
const caseList = z.object({
	areas: z.array(
		z.object({
			name: z.string(),
			title: z.string(),
			description: z.string(),
			cases: z.array(conformanceCase),
		})
	),
	invariants: z.array(
		z.object({
			id: z.string(),
			title: z.string(),
			expectation: z.string(),
			needs: z.array(z.string()),
			covers: z.array(z.string()),
		})
	),
	uncovered: z.array(z.object({ citation: z.string(), reason: z.string() })),
});

// The component table, in the file's order.
const componentTable = z.object({
	components: z.array(
		z.object({
			id: z.string(),
			description: z.string(),
			issue: z.number().int(),
			built: z.boolean(),
		})
	),
});

/**
 * Loads the conformance case list, in one entry whose ID is `case-list`: its areas, cases,
 * invariants and uncovered anchors, with each case's and invariant's left-out fields given the
 * defaults its schema states.
 *
 * @returns A loader for a content collection, typed with its schema, from which Astro infers the
 *   entry's type.
 */
export function conformanceCases(): Loader & { schema: typeof caseList } {
	const loader = file(repositoryFileUrl(conformanceCasesFilePath).href, {
		parser: (text) => ({
			'case-list': caseListOf(parse(text), defaultsOf('case'), defaultsOf('invariant')),
		}),
	});
	return { name: 'conformance-cases', load: loader.load, schema: caseList };
}

/**
 * Loads the components the conformance cases need, in one entry whose ID is `components`.
 *
 * @returns A loader for a content collection, typed with its schema, from which Astro infers the
 *   entry's type.
 */
export function conformanceComponents(): Loader & { schema: typeof componentTable } {
	const where = conformanceComponentsFilePath;
	const loader = file(repositoryFileUrl(where).href, {
		parser: (text) => ({
			components: {
				components: Object.entries(recordOf(parse(text), where)).map(([id, component]) => ({
					id,
					...recordOf(component, `${where}'s ${id}`),
				})),
			},
		}),
	});
	return { name: 'conformance-components', load: loader.load, schema: componentTable };
}

function caseListOf(
	document: unknown,
	caseDefaults: Readonly<Record<string, unknown>>,
	invariantDefaults: Readonly<Record<string, unknown>>
): Record<string, unknown> {
	const where = conformanceCasesFilePath;
	const root = recordOf(document, where);
	return {
		areas: Object.entries(recordOf(root.areas, `${where}'s areas`)).map(([name, area]) => {
			const fields = recordOf(area, `${where}'s ${name}`);
			const cases = recordOf(fields.cases, `${where}'s ${name} cases`);
			return {
				...fields,
				name,
				cases: Object.entries(cases).map(([id, definition]) => ({
					...caseDefaults,
					...recordOf(definition, `${where}'s ${id}`),
					id,
				})),
			};
		}),
		invariants: Object.entries(recordOf(root.invariants, `${where}'s invariants`)).map(
			([id, invariant]) => ({
				...invariantDefaults,
				...recordOf(invariant, `${where}'s ${id}`),
				id,
			})
		),
		uncovered: Object.entries(recordOf(root.uncovered, `${where}'s uncovered`)).map(
			([citation, reason]) => ({ citation, reason })
		),
	};
}

// The default of each field of a case or an invariant that has one, as cases.schema.json states it.
function defaultsOf(definition: 'case' | 'invariant'): Record<string, unknown> {
	const where = conformanceCasesSchemaPath;
	const text = readFileSync(repositoryFileUrl(where), 'utf-8');
	const definitions = recordOf(recordOf(JSON.parse(text), where).$defs, `${where}'s $defs`);
	const properties = recordOf(
		recordOf(definitions[definition], `${where}'s ${definition}`).properties,
		where
	);
	return Object.fromEntries(
		Object.entries(properties).flatMap(([key, property]) =>
			isRecord(property) && 'default' in property ? [[key, property.default]] : []
		)
	);
}
