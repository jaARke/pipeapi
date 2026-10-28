import { statSync } from 'node:fs';
import { root } from 'astro:config/server';
import { getEntry, type CollectionEntry } from 'astro:content';
import {
	connectorApiFilePath,
	connectorApiPageSlug,
	contractPathOnGitHub,
	protocolPageSlug,
	protocolRouteSlug,
	protocolVersionOfPage,
	protocolVersions,
	type ProtocolVersion,
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

/** The index of the connector API's file: a list of entries for each section. */
export type ConnectorApiIndex = CollectionEntry<'connectorApi'>['data'];

/** A section of the connector API's index, such as `errors`. */
export type ConnectorApiSection = keyof ConnectorApiIndex;

/** One name the connector API defines, with what its section's table shows of it. */
export type ConnectorApiEntry = ConnectorApiIndex[ConnectorApiSection][number];

/**
 * Reads one section of a protocol version's registry, sorted by name, so a table lists it in the
 * same order on every platform. Names that are numbers sort as numbers.
 *
 * @param version - The protocol version.
 * @param section - The section's key in the version's `registry.yaml`, such as `rejections`.
 * @returns The section's entries.
 * @throws An `Error` when the registry has no such section.
 */
export async function registrySection(
	version: ProtocolVersion,
	section: string
): Promise<readonly RegistryEntry[]> {
	const entry = await getEntry(`${version}Registry`, section);
	if (entry === undefined) {
		throw new Error(`protocol/${version}/registry.yaml has no section named ${section}.`);
	}
	return Object.entries(entry.data)
		.map(([name, fields]) => ({ name, fields: new Map<string, unknown>(Object.entries(fields)) }))
		.toSorted((a, b) => a.name.localeCompare(b.name, 'en', { numeric: true }));
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
	const entry = await getEntry('connectorApi', 'connector-api');
	if (entry === undefined) {
		throw new Error(`${connectorApiFilePath} did not load.`);
	}
	const { data } = entry;
	if (!isConnectorApiSection(data, section)) {
		const known = Object.keys(data).join(', ');
		throw new Error(`The connector API has no section named ${section}; it has ${known}.`);
	}
	return data[section];
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
 * @returns The citation, whose text is the name as its file spells it, or a constant's value.
 * @throws An `Error` that names the name when the files don't hold it.
 */
export async function citationOf(
	version: ProtocolVersion,
	name: string,
	section: string | undefined
): Promise<Citation> {
	const page = protocolPageSlug(version);
	if (section !== undefined || name.startsWith('PIPEAPI_')) {
		const kind = section ?? 'environment_variables';
		const entry = (await registrySection(version, kind)).find((found) => found.name === name);
		if (entry === undefined) {
			throw new Error(`${name} is not in protocol/${version}/registry.yaml's ${kind}.`);
		}
		const value = entry.fields.get('value');
		return {
			text: typeof value === 'string' ? value : name,
			href: pageHref(page, anchorOf(kind, name)),
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
	return { text: header.name, href: pageHref(page, anchorOf('headers', header.name)) };
}

/**
 * Resolves a name a page cites against the connector API's file.
 *
 * @param name - The name, as the file spells it.
 * @param section - The section of the file that holds the name, such as `errors`.
 * @returns The citation, whose text is the name and whose link is its row on the connector API's
 *   page.
 * @throws An `Error` that names the name when the section doesn't hold it.
 */
export async function connectorApiCitationOf(name: string, section: string): Promise<Citation> {
	const entry = (await connectorApiSection(section)).find((found) => found.name === name);
	if (entry === undefined) {
		throw new Error(`${name} is not in ${connectorApiFilePath}'s ${section}.`);
	}
	return { text: entry.name, href: pageHref(connectorApiPageSlug, anchorOf(section, entry.name)) };
}

/**
 * Links to a file or a directory under `protocol/` on GitHub, and checks that the repository holds
 * it, so a link to a file that moved or was renamed fails the build.
 *
 * @param path - The path from the repository's root, such as `protocol/v1/vectors/`. A
 *   directory's path ends in a slash.
 * @returns The URL of the file's or the directory's page on GitHub.
 * @throws An `Error` that names the path when it isn't under `protocol/`, or the repository has no
 *   such file or directory.
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
	const base = import.meta.env.BASE_URL.replace(/\/$/, '');
	return `${base}/${slug}/${anchor === undefined ? '' : `#${anchor}`}`;
}

function isConnectorApiSection(
	index: ConnectorApiIndex,
	section: string
): section is ConnectorApiSection {
	return Object.hasOwn(index, section);
}
