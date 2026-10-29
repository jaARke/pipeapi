import { fileURLToPath } from 'node:url';
import { file, type Loader } from 'astro/loaders';
import { z } from 'astro/zod';
import { compileFromFile } from 'json-schema-to-typescript';
import { parse } from 'yaml';
import {
	connectorApiFilePath,
	connectorApiFileUrl,
	contractStatuses,
	protocolFileUrl,
	type ContractStatus,
	type ProtocolVersion,
} from '../protocol';
import { schemaText } from './json-schema';
import { arrayOf, recordOf, stringOf } from './narrow';

// `just lint` validates the contract files against their JSON Schemas, so the site takes the
// registry's data as it is, typed from the same schema, rather than declaring its shape a second
// time.
const passthrough = z.looseObject({});

// The OpenAPI document's text, and the index of it that pages and the sidebar read. The index is
// the site's own view of the document, which vacuum validates in `just lint`.
const openApiDocument = z.object({
	source: z.string(),
	summary: z.string(),
	tags: z.array(z.object({ name: z.string(), summary: z.string() })),
	routes: z.array(
		z.object({
			path: z.string(),
			method: z.string(),
			operationId: z.string(),
			description: z.string(),
		})
	),
	headers: z.array(
		z.object({
			name: z.string(),
			direction: z.enum(['request', 'response']),
			description: z.string(),
		})
	),
});

type OpenApiDocument = z.infer<typeof openApiDocument>;

// One name the connector API defines, with what its section's table shows of it: an option's type,
// default and environment variable, a union member's fields, a log event's level, or a constant's
// value with its unit.
const connectorApiEntry = z.object({
	name: z.string(),
	description: z.string(),
	type: z.string().optional(),
	default: z.string().optional(),
	environmentVariable: z.string().optional(),
	level: z.string().optional(),
	value: z.string().optional(),
	fields: z
		.array(
			z.object({
				name: z.string(),
				type: z.string(),
				required: z.boolean(),
				description: z.string(),
			})
		)
		.optional(),
});

// The index of the connector API's file that pages read: its status, and each section in the file's
// order. It is the site's own view of the file, which `just lint` validates against its
// meta-schema.
const connectorApiIndex = z.object({
	status: z.enum(contractStatuses),
	sections: z.object({
		options: z.array(connectorApiEntry),
		request_options: z.array(connectorApiEntry),
		events: z.array(connectorApiEntry),
		lost_reasons: z.array(connectorApiEntry),
		errors: z.array(connectorApiEntry),
		log_events: z.array(connectorApiEntry),
		constants: z.array(connectorApiEntry),
	}),
});

type ConnectorApiEntry = z.infer<typeof connectorApiEntry>;
type ConnectorApiIndex = z.infer<typeof connectorApiIndex>;

// The fixed fields of an OpenAPI 3.2 path item that hold an operation.
const operationMethods = [
	'get',
	'put',
	'post',
	'delete',
	'options',
	'head',
	'patch',
	'trace',
	'query',
] as const;

/**
 * Loads a protocol version's `registry.yaml`, in one entry whose ID is the version: the registry as
 * it is, with the version's status and each section, typed from `registry.schema.json`.
 *
 * @param version - The protocol version whose registry to read.
 * @returns A loader for a content collection.
 */
export function registry(version: ProtocolVersion): Loader {
	const loader = file(protocolFileUrl(version, 'registry.yaml').href, {
		parser: (text) => ({ [version]: recordOf(parse(text), 'registry.yaml') }),
	});
	return {
		name: 'protocol-registry',
		load: loader.load,
		createSchema: async () => {
			const schema = fileURLToPath(protocolFileUrl(version, 'registry.schema.json'));
			const types = await compileFromFile(schema, { bannerComment: '', format: false });
			return { schema: passthrough, types: `${types}\nexport type Entry = Registry;\n` };
		},
	};
}

/**
 * Loads a protocol version's `openapi.yaml`, in one entry whose ID is the version: the document's
 * text, for a page to show it as it is; its summary and tags, for the sidebar and the index pages
 * to name its routes by; and its reserved routes and headers, for pages to list and cite them.
 *
 * @param version - The protocol version whose OpenAPI document to read.
 * @returns A loader for a content collection, typed with its schema, from which Astro infers the
 *   entry's type.
 */
export function openApi(version: ProtocolVersion): Loader & { schema: typeof openApiDocument } {
	const loader = file(protocolFileUrl(version, 'openapi.yaml').href, {
		parser: (text) => ({ [version]: indexOf(text, parse(text)) }),
	});
	return { name: 'protocol-openapi', load: loader.load, schema: openApiDocument };
}

/**
 * Loads the connector API's file, in one entry whose ID is `connector-api`: its status, and its
 * options, lifecycle events, errors, log events and constants, each with what its table shows, for
 * pages to list and cite them.
 *
 * @returns A loader for a content collection, typed with its schema, from which Astro infers the
 *   entry's type.
 */
export function connectorApi(): Loader & { schema: typeof connectorApiIndex } {
	const loader = file(connectorApiFileUrl().href, {
		parser: (text) => ({ 'connector-api': connectorApiIndexOf(JSON.parse(text)) }),
	});
	return { name: 'connector-api', load: loader.load, schema: connectorApiIndex };
}

function indexOf(source: string, document: unknown): OpenApiDocument {
	const root = recordOf(document, 'openapi.yaml');
	const info = recordOf(root.info, 'openapi.yaml info');
	return {
		source,
		summary: stringOf(info.summary, 'openapi.yaml info summary'),
		tags: tagsOf(root),
		routes: routesOf(root),
		headers: headersOf(root),
	};
}

// Each tag by its name, which operations use, and its summary, which OpenAPI 3.2 gives for display.
function tagsOf(document: Record<string, unknown>): OpenApiDocument['tags'] {
	return arrayOf(document.tags ?? [], 'openapi.yaml tags').map((tag, index) => {
		const where = `openapi.yaml's tag ${String(index + 1)}`;
		const fields = recordOf(tag, where);
		return {
			name: stringOf(fields.name, `${where} name`),
			summary: stringOf(fields.summary, `${where} summary`),
		};
	});
}

function routesOf(document: Record<string, unknown>): OpenApiDocument['routes'] {
	const routes: OpenApiDocument['routes'] = [];
	for (const [path, item] of Object.entries(recordOf(document.paths, 'openapi.yaml paths'))) {
		const pathItem = recordOf(item, `openapi.yaml's ${path}`);
		const operations: [string, unknown][] = operationMethods.flatMap((method) =>
			pathItem[method] === undefined ? [] : [[method, pathItem[method]]]
		);
		const additional = pathItem.additionalOperations;
		if (additional !== undefined) {
			operations.push(...Object.entries(recordOf(additional, `openapi.yaml's ${path}`)));
		}
		for (const [method, operation] of operations) {
			const where = `openapi.yaml's ${method.toUpperCase()} ${path}`;
			const fields = recordOf(operation, where);
			routes.push({
				path,
				method: method.toUpperCase(),
				operationId: stringOf(fields.operationId, `${where} operationId`),
				description: stringOf(fields.description, `${where} description`),
			});
		}
	}
	return routes;
}

// Every header is a component: a request header in parameters, a response header in headers
// under its own name.
function headersOf(document: Record<string, unknown>): OpenApiDocument['headers'] {
	const components = recordOf(document.components, 'openapi.yaml components');
	const headers: OpenApiDocument['headers'] = [];
	const parameters = recordOf(components.parameters ?? {}, 'openapi.yaml parameters');
	for (const [key, parameter] of Object.entries(parameters)) {
		const where = `openapi.yaml's parameter ${key}`;
		const fields = recordOf(parameter, where);
		if (fields.in === 'header') {
			headers.push({
				name: stringOf(fields.name, `${where} name`),
				direction: 'request',
				description: stringOf(fields.description, `${where} description`),
			});
		}
	}
	const responseHeaders = recordOf(components.headers ?? {}, 'openapi.yaml headers');
	for (const [name, header] of Object.entries(responseHeaders)) {
		const where = `openapi.yaml's header ${name}`;
		headers.push({
			name,
			direction: 'response',
			description: stringOf(recordOf(header, where).description, `${where} description`),
		});
	}
	return headers;
}

function connectorApiIndexOf(document: unknown): ConnectorApiIndex {
	const root = recordOf(document, connectorApiFilePath);
	const definitions = recordOf(root.$defs, `${connectorApiFilePath}'s $defs`);
	return {
		status: statusOf(root['x-status'], `${connectorApiFilePath}'s x-status`),
		sections: {
			options: optionsOf(definitions, 'options'),
			request_options: optionsOf(definitions, 'request_options'),
			events: unionOf(definitions, 'event', 'type'),
			lost_reasons: enumerationOf(definitions, 'lost_reason'),
			errors: unionOf(definitions, 'error', 'code'),
			log_events: unionOf(definitions, 'log_record', 'event'),
			constants: constantsOf(root['x-constants']),
		},
	};
}

function statusOf(value: unknown, where: string): ContractStatus {
	const status = contractStatuses.find((known) => known === value);
	if (status === undefined) {
		throw new Error(`${where} is not one of ${contractStatuses.join(', ')}.`);
	}
	return status;
}

// The properties of an object of options, each with its type, its default and its variable.
function optionsOf(
	definitions: Readonly<Record<string, unknown>>,
	object: string
): ConnectorApiEntry[] {
	const where = `${connectorApiFilePath}'s ${object}`;
	const properties = recordOf(recordOf(definitions[object], where).properties, where);
	return Object.entries(properties).map(([name, option]) => {
		const fields = recordOf(option, `${where}.${name}`);
		const variable = fields['x-environment-variable'];
		return {
			name,
			description: stringOf(fields.description, `${where}.${name} description`),
			type: schemaText(fields, definitions, `${where}.${name}`),
			...('default' in fields ? { default: JSON.stringify(fields.default) } : {}),
			...(variable === undefined
				? {}
				: {
						environmentVariable: stringOf(variable, `${where}.${name} x-environment-variable`),
					}),
		};
	});
}

// A union's members, each named by its tag's constant, with the fields only it has. A log
// record's members also carry their level, which the table shows apart from the fields.
function unionOf(
	definitions: Readonly<Record<string, unknown>>,
	union: string,
	tag: string
): ConnectorApiEntry[] {
	const where = `${connectorApiFilePath}'s ${union}`;
	const base = recordOf(definitions[union], where);
	const baseRequired = arrayOf(base.required ?? [], `${where} required`);
	return arrayOf(base.oneOf, `${where} oneOf`).map((member, index) => {
		const memberWhere = `${where} member ${String(index + 1)}`;
		const fields = recordOf(member, memberWhere);
		const properties = recordOf(fields.properties, `${memberWhere} properties`);
		const required = [
			...baseRequired,
			...arrayOf(fields.required ?? [], `${memberWhere} required`),
		];
		const constantOf = (key: string): string =>
			stringOf(recordOf(properties[key], `${memberWhere} ${key}`).const, `${memberWhere} ${key}`);
		const name = constantOf(tag);
		return {
			name,
			description: stringOf(fields.description, `${where}.${name} description`),
			...(properties.level === undefined ? {} : { level: constantOf('level') }),
			fields: Object.entries(properties)
				.filter(([key]) => key !== tag && key !== 'level')
				.map(([key, property]) => ({
					name: key,
					type: schemaText(property, definitions, `${where}.${name}.${key}`),
					required: required.includes(key),
					description: stringOf(
						recordOf(property, `${where}.${name}.${key}`).description,
						`${where}.${name}.${key} description`
					),
				})),
		};
	});
}

// The values of an enumeration, each named by its constant.
function enumerationOf(
	definitions: Readonly<Record<string, unknown>>,
	enumeration: string
): ConnectorApiEntry[] {
	const where = `${connectorApiFilePath}'s ${enumeration}`;
	const values = arrayOf(recordOf(definitions[enumeration], where).oneOf, `${where} oneOf`);
	return values.map((value, index) => {
		const valueWhere = `${where} value ${String(index + 1)}`;
		const fields = recordOf(value, valueWhere);
		const name = stringOf(fields.const, `${valueWhere} const`);
		return { name, description: stringOf(fields.description, `${where}.${name} description`) };
	});
}

function constantsOf(constants: unknown): ConnectorApiEntry[] {
	const where = `${connectorApiFilePath}'s x-constants`;
	return Object.entries(recordOf(constants, where)).map(([name, constant]) => {
		const fields = recordOf(constant, `${where}.${name}`);
		const value =
			typeof fields.seconds === 'number'
				? `${String(fields.seconds)} s`
				: `${String(fields.bytes)} bytes`;
		return {
			name,
			description: stringOf(fields.description, `${where}.${name} description`),
			value,
		};
	});
}
