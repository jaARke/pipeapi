import { statSync } from 'node:fs';
import { root } from 'astro:config/server';
import { getEntry, type CollectionEntry } from 'astro:content';
import { recordOf } from '../../loaders/narrow';
import {
	connectorApiFilePath,
	connectorApiSlug,
	contractPathOnGitHub,
	protocolRouteSlug,
	protocolSpecSlug,
	protocolVersionOfDocument,
	protocolVersionOfPage,
	protocolVersions,
	type ContractStatus,
	type ProtocolVersion,
	type SpecDocument,
} from '../../protocol';

/** One entry of a registry section. */
export interface RegistryEntry {
	readonly name: string;
	/** The entry's fields by their keys in `registry.yaml`, its description among them. */
	readonly fields: ReadonlyMap<string, unknown>;
}

/** A name a page cites: the text it shows, and the link to the row or page that defines it. */
export interface Citation {
	readonly text: string;
	readonly href: string;
}

/** A table row of a contract's page: its anchor, such as `rejections.draining`, and its link. */
export interface ContractRow {
	readonly anchor: string;
	readonly href: string;
}

/** The sections of the connector API's index: a list of entries for each. */
export type ConnectorApiIndex = CollectionEntry<'connectorApi'>['data']['sections'];

/** A section of the connector API's index, such as `errors`. */
export type ConnectorApiSection = keyof ConnectorApiIndex;

/** One name the connector API defines, with what its section's table shows of it. */
export type ConnectorApiEntry = ConnectorApiIndex[ConnectorApiSection][number];

/** A table of a protocol version's spec: a section of its registry, its routes or its headers. */
export type ProtocolTable<V extends ProtocolVersion = ProtocolVersion> =
	| Exclude<keyof CollectionEntry<`${V}Registry`>['data'], typeof registryStatusKey>
	| 'routes'
	| 'headers';

/**
 * Reads one section of a protocol version's registry, sorted by name, so a table lists it in the
 * same order on every platform. Names that are numbers sort as numbers.
 *
 * @param version - The protocol version.
 * @param section - The section's key in the version's `registry.yaml`, such as `rejections`.
 * @returns The section's entries.
 * @throws An `Error` when the registry didn't load or has no such section.
 */
export async function registrySection(
	version: ProtocolVersion,
	section: string
): Promise<readonly RegistryEntry[]> {
	const where = `protocol/${version}/registry.yaml`;
	const registry = recordOf(await registryOf(version), where);
	if (section === registryStatusKey || !Object.hasOwn(registry, section)) {
		throw new Error(`${where} has no section named ${section}.`);
	}
	return Object.entries(recordOf(registry[section], `${where}'s ${section}`))
		.map(([name, fields]) => ({
			name,
			fields: new Map(Object.entries(recordOf(fields, `${where}'s ${section}.${name}`))),
		}))
		.toSorted((a, b) => a.name.localeCompare(b.name, 'en', { numeric: true }));
}

/**
 * Reads a protocol version's status, which its `registry.yaml` states.
 *
 * @param version - The protocol version.
 * @returns The status.
 * @throws An `Error` when the registry didn't load.
 */
export async function protocolStatus(version: ProtocolVersion): Promise<ContractStatus> {
	return (await registryOf(version)).status;
}

/**
 * Reads a protocol version's OpenAPI document: its text, and its reserved routes and headers in
 * the order the document gives them.
 *
 * @param version - The protocol version.
 * @returns The document's collection entry data.
 * @throws An `Error` when the document didn't load.
 */
export async function openApiDocument(
	version: ProtocolVersion
): Promise<CollectionEntry<`${ProtocolVersion}OpenApi`>['data']> {
	const entry = await getEntry(`${version}OpenApi`, version);
	if (entry === undefined) {
		throw new Error(`protocol/${version}/openapi.yaml did not load.`);
	}
	return entry.data;
}

/**
 * Reads one section of the connector API's file, in the file's order.
 *
 * @param section - The section, such as `options`. Pages pass it as text, unchecked.
 * @returns The section's entries.
 * @throws An `Error` when the file didn't load, or has no such section.
 */
export async function connectorApiSection(section: string): Promise<readonly ConnectorApiEntry[]> {
	const { sections } = await connectorApiOf();
	if (!isConnectorApiSection(sections, section)) {
		const known = Object.keys(sections).join(', ');
		throw new Error(`The connector API has no section named ${section}; it has ${known}.`);
	}
	return sections[section];
}

/**
 * Reads the connector API's status, which its file states.
 *
 * @returns The status.
 * @throws An `Error` when the file didn't load.
 */
export async function connectorApiStatus(): Promise<ContractStatus> {
	return (await connectorApiOf()).status;
}

/**
 * Reads the status of the contract a document of the spec states: a protocol version's, or the
 * connector API's.
 *
 * @param document - The document.
 * @returns The status.
 * @throws An `Error` when the contract's file didn't load.
 */
export async function documentStatus(document: SpecDocument): Promise<ContractStatus> {
	const version = protocolVersionOfDocument(document);
	return version === undefined ? connectorApiStatus() : protocolStatus(version);
}

/**
 * Names the page of a protocol version's specification that renders one of its tables, where a
 * citation of one of its rows links.
 *
 * @param version - The protocol version.
 * @param table - A section of the version's registry, `routes` or `headers`. Pages pass it as
 *   text, unchecked.
 * @returns The page's slug, without the site's base path.
 * @throws An `Error` when the version has no such table.
 */
export function protocolTablePage(version: ProtocolVersion, table: string): string {
	return tablePage(protocolSpecSlug(version), protocolTablePages[version], table);
}

/**
 * Names the page of the connector API that renders one of its sections' tables, where a citation
 * of one of its rows links.
 *
 * @param section - The section, such as `errors`. Pages pass it as text, unchecked.
 * @returns The page's slug, without the site's base path.
 * @throws An `Error` when the connector API has no such section.
 */
export function connectorApiTablePage(section: string): string {
	return tablePage(connectorApiSlug, connectorApiTablePages, section);
}

/**
 * Checks that a table renders on the page declared for it, so that every citation of its rows
 * links the page that holds them.
 *
 * @param pageId - The ID of the page that renders the table.
 * @param declared - The slug of the table's declared page.
 * @param table - What the table renders, for the error, such as `protocol/v1/registry.yaml's
 *   rejections`.
 * @throws An `Error` that names both pages when the table renders on another page.
 */
export function checkTablePage(pageId: string, declared: string, table: string): void {
	if (pageId !== declared) {
		throw new Error(
			`The table of ${table} renders on ${pageId}, but docs/src/components/protocol/contract.ts gives it the page ${declared}. Render it there, or change its page.`
		);
	}
}

/**
 * Names the anchor of the table row on a page that defines a name.
 *
 * @param kind - The registry or connector API section that holds the name, or `headers` for a
 *   header.
 * @param name - The name, as its file spells it.
 * @returns An anchor such as `rejections.invalid_session`, which no heading's anchor can equal.
 */
export function anchorOf(kind: string, name: string): string {
	return `${kind}.${name}`;
}

/**
 * Finds the protocol version whose files a citation reads.
 *
 * @param pageId - The citing page's ID.
 * @param given - The version the citation names, if any. Pages pass it as text, unchecked.
 * @returns The version the citation names, or else the version whose pages hold the page.
 * @throws An `Error` when the citation names no version the site renders, or names none on a page
 *   outside every version's pages.
 */
export function citedVersion(pageId: string, given: string | undefined): ProtocolVersion {
	if (given === undefined) {
		const version = protocolVersionOfPage(pageId);
		if (version === undefined) {
			throw new Error(`A citation on ${pageId} needs a version, such as version="v1".`);
		}
		return version;
	}
	const version = protocolVersions.find((known) => known === given);
	if (version === undefined) {
		throw new Error(`A citation on ${pageId} names ${given}, which is not a protocol version.`);
	}
	return version;
}

/**
 * Resolves a name a page cites against a protocol version's files, by the name's form: a
 * `PIPEAPI_` variable against the registry's environment variables, a path against the OpenAPI
 * document's routes, and any other name against its headers, case-insensitively. A name of any
 * other kind is cited with the registry section that holds it.
 *
 * @param version - The protocol version whose files hold the name.
 * @param name - The name, or for a route its path.
 * @param section - The registry section that holds the name, for a name of another kind.
 * @returns The citation, whose text is the name as its file spells it, or a constant's value, and
 *   whose link is its row on the page of its table, or a route's own page.
 * @throws An `Error` that names the name when the files don't hold it.
 */
export async function citationOf(
	version: ProtocolVersion,
	name: string,
	section: string | undefined
): Promise<Citation> {
	if (section !== undefined || name.startsWith('PIPEAPI_')) {
		const kind = section ?? 'environment_variables';
		const entry = (await registrySection(version, kind)).find((found) => found.name === name);
		if (entry === undefined) {
			throw new Error(`${name} is not in protocol/${version}/registry.yaml's ${kind}.`);
		}
		const value = entry.fields.get('value');
		return {
			text: typeof value === 'string' ? value : name,
			href: pageHref(protocolTablePage(version, kind), anchorOf(kind, name)),
		};
	}
	const document = await openApiDocument(version);
	if (name.startsWith('/')) {
		const route = document.routes.find((found) => found.path === name);
		if (route === undefined) {
			throw new Error(`${name} is not a route in protocol/${version}/openapi.yaml.`);
		}
		return { text: route.path, href: pageHref(protocolRouteSlug(version, route.operationId)) };
	}
	const header = document.headers.find((found) => found.name.toLowerCase() === name.toLowerCase());
	if (header === undefined) {
		throw new Error(`${name} is not a header in protocol/${version}/openapi.yaml.`);
	}
	return {
		text: header.name,
		href: pageHref(protocolTablePage(version, 'headers'), anchorOf('headers', header.name)),
	};
}

/**
 * Resolves a name a page cites against the connector API's file.
 *
 * @param name - The name, as the file spells it.
 * @param section - The section of the file that holds the name, such as `errors`.
 * @returns The citation, whose text is the name and whose link is its row on the page of its
 *   section's table.
 * @throws An `Error` that names the name when the section doesn't hold it.
 */
export async function connectorApiCitationOf(name: string, section: string): Promise<Citation> {
	const entry = (await connectorApiSection(section)).find((found) => found.name === name);
	if (entry === undefined) {
		throw new Error(`${name} is not in ${connectorApiFilePath}'s ${section}.`);
	}
	return {
		text: entry.name,
		href: pageHref(connectorApiTablePage(section), anchorOf(section, entry.name)),
	};
}

/**
 * Lists every table row of a protocol version's specification, each linking the page of its
 * table: each registry entry, by its section and name, then each reserved route, as
 * `routes.<operationId>`, then each header, as `headers.<name>`.
 *
 * @param version - The protocol version.
 * @returns The rows, each section in the file's order.
 * @throws An `Error` when the version's files didn't load.
 */
export async function protocolRows(version: ProtocolVersion): Promise<readonly ContractRow[]> {
	const registry = recordOf(await registryOf(version), `protocol/${version}/registry.yaml`);
	const rows: ContractRow[] = [];
	for (const section of Object.keys(registry).filter((key) => key !== registryStatusKey)) {
		const page = protocolTablePage(version, section);
		for (const { name } of await registrySection(version, section)) {
			rows.push(rowOf(page, anchorOf(section, name)));
		}
	}
	const { routes, headers } = await openApiDocument(version);
	const routesPage = protocolTablePage(version, 'routes');
	const headersPage = protocolTablePage(version, 'headers');
	rows.push(...routes.map(({ operationId }) => rowOf(routesPage, anchorOf('routes', operationId))));
	rows.push(...headers.map(({ name }) => rowOf(headersPage, anchorOf('headers', name))));
	return rows;
}

/**
 * Lists every table row of the connector API, by its section and name, each linking the page of
 * its section's table.
 *
 * @returns The rows, in the file's order.
 * @throws An `Error` when the file didn't load.
 */
export async function connectorApiRows(): Promise<readonly ContractRow[]> {
	const { sections } = await connectorApiOf();
	return Object.entries(sections).flatMap(([section, entries]) => {
		const page = connectorApiTablePage(section);
		return entries.map(({ name }) => rowOf(page, anchorOf(section, name)));
	});
}

/**
 * Links to a file or a directory of the contract on GitHub, and checks that the repository holds
 * it, so a link to a file that moved or was renamed fails the build.
 *
 * @param path - The path from the repository's root, such as `protocol/v1/vectors/`. A
 *   directory's path ends in a slash.
 * @returns The URL of the file's or the directory's page on GitHub.
 * @throws An `Error` that names the path when it isn't under one of the contract's directories, or
 *   the repository has no such file or directory.
 */
export function checkedContractLink(path: string): string {
	const href = contractPathOnGitHub(path);
	// The site's root is docs/, one directory below the repository's.
	const stats = statSync(new URL(`../${path}`, root), { throwIfNoEntry: false });
	const directory = path.endsWith('/');
	if (stats?.isDirectory() !== directory) {
		throw new Error(`The repository has no ${directory ? 'directory' : 'file'} named ${path}.`);
	}
	return href;
}

/**
 * Links to a page of the site, from any page.
 *
 * @param slug - The page's slug, without the site's base path.
 * @param anchor - An anchor on the page.
 * @returns The link, with the site's base path.
 */
export function pageHref(slug: string, anchor?: string): string {
	return `${basePath()}/${slug}/${anchor === undefined ? '' : `#${anchor}`}`;
}

/**
 * Finds the page a link of the site leads to, as {@link pageHref} writes the link.
 *
 * @param href - The link, with the site's base path and without an anchor.
 * @returns The page's ID, which is its slug without the site's base path, or `undefined` for a
 *   link outside the site.
 */
export function pageIdOf(href: string): string | undefined {
	const prefix = `${basePath()}/`;
	return href.startsWith(prefix) ? href.slice(prefix.length).replace(/\/$/, '') : undefined;
}

// The registry's one top-level property that isn't a section.
const registryStatusKey = 'status';

// The page of each protocol version's specification that renders each of its tables, by the page's
// name in the version's directory. A new table fails to compile until it has one.
const protocolTablePages = {
	v1: {
		environment_variables: 'connecting',
		constants: 'registry',
		rejections: 'requests',
		durations: 'registry',
		exit_codes: 'lifetime',
		features: 'versioning',
		lease_event_types: 'leases',
		lease_end_reasons: 'leases',
		protocol_versions: 'versioning',
		routes: 'requests',
		headers: 'requests',
	},
} as const satisfies {
	readonly [V in ProtocolVersion]: Readonly<Record<ProtocolTable<V>, string>>;
};

// The page of the connector API that renders each section's table, by its name in the directory.
const connectorApiTablePages = {
	options: 'options',
	request_options: 'requests',
	events: 'lifecycle-events',
	lost_reasons: 'lifecycle-events',
	errors: 'errors',
	log_events: 'logging',
	constants: 'constants',
} as const satisfies Readonly<Record<ConnectorApiSection, string>>;

function tablePage(
	directory: string,
	pages: Readonly<Record<string, string>>,
	table: string
): string {
	const page = Object.hasOwn(pages, table) ? pages[table] : undefined;
	if (page === undefined) {
		throw new Error(`${directory} has no table named ${table}.`);
	}
	return `${directory}/${page}`;
}

// The site's base path without its final slash, such as /pipeapi.
function basePath(): string {
	return import.meta.env.BASE_URL.replace(/\/$/, '');
}

function rowOf(page: string, anchor: string): ContractRow {
	return { anchor, href: pageHref(page, anchor) };
}

async function registryOf(
	version: ProtocolVersion
): Promise<CollectionEntry<`${ProtocolVersion}Registry`>['data']> {
	const entry = await getEntry(`${version}Registry`, version);
	if (entry === undefined) {
		throw new Error(`protocol/${version}/registry.yaml did not load.`);
	}
	return entry.data;
}

async function connectorApiOf(): Promise<CollectionEntry<'connectorApi'>['data']> {
	const entry = await getEntry('connectorApi', 'connector-api');
	if (entry === undefined) {
		throw new Error(`${connectorApiFilePath} did not load.`);
	}
	return entry.data;
}

function isConnectorApiSection(
	index: ConnectorApiIndex,
	section: string
): section is ConnectorApiSection {
	return Object.hasOwn(index, section);
}
