import { fileURLToPath } from 'node:url';
import { file, type Loader } from 'astro/loaders';
import { z } from 'astro/zod';
import { compileFromFile } from 'json-schema-to-typescript';
import { parse } from 'yaml';
import { protocolFileUrl, type ProtocolVersion } from '../protocol';

// `just lint` validates the contract files against their JSON Schemas, so the site takes their data
// as it is, typed from the same schemas, rather than declaring their shape a second time.
const passthrough = z.looseObject({});

/**
 * Loads one section of a protocol version's `registry.yaml`, with an entry for each name in it.
 * Each entry's type comes from `registry.schema.json`.
 *
 * @param version - The protocol version whose registry to read.
 * @param section - The section's key in `registry.yaml`, such as `environment_variables`.
 * @returns A loader for a content collection.
 */
export function registrySection(version: ProtocolVersion, section: string): Loader {
	const loader = file(protocolFileUrl(version, 'registry.yaml').href, {
		parser: (text) => sectionOf(parse(text), section),
	});
	return {
		name: 'protocol-registry',
		load: loader.load,
		createSchema: async () => {
			const schema = fileURLToPath(protocolFileUrl(version, 'registry.schema.json'));
			const types = await compileFromFile(schema, { bannerComment: '', format: false });
			return {
				schema: passthrough,
				types: `${types}\nexport type Entry = Registry[${JSON.stringify(section)}][string];\n`,
			};
		},
	};
}

/**
 * Loads a protocol version's `openapi.yaml` as its text, for a page to show it as it is, in one
 * entry whose ID is the version.
 *
 * @param version - The protocol version whose OpenAPI document to read.
 * @returns A loader for a content collection.
 */
export function openApiSource(version: ProtocolVersion): Loader {
	const loader = file(protocolFileUrl(version, 'openapi.yaml').href, {
		parser: (text) => ({ [version]: { source: text } }),
	});
	return {
		name: 'protocol-openapi',
		load: loader.load,
		createSchema: () =>
			Promise.resolve({
				schema: passthrough,
				types: 'export interface Entry {\n\treadonly source: string;\n}\n',
			}),
	};
}

// What file() takes from a parser: a mapping from each entry's ID to its data.
function sectionOf(registry: unknown, section: string): Record<string, Record<string, unknown>> {
	const entries = isRecord(registry) ? registry[section] : undefined;
	if (!isRecord(entries)) {
		throw new Error(`registry.yaml has no section named ${section}.`);
	}
	const result: Record<string, Record<string, unknown>> = {};
	for (const [name, entry] of Object.entries(entries)) {
		if (!isRecord(entry)) {
			throw new Error(`registry.yaml's ${section}.${name} is not a mapping.`);
		}
		result[name] = entry;
	}
	return result;
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}
