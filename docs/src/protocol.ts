/** The repository the site documents, whose `main` branch holds the contract files. */
export const repositoryUrl = 'https://github.com/jaARke/pipeapi';

/** The protocol versions whose contract files the site renders, each a directory of `protocol/`. */
export const protocolVersions = ['v1'] as const;

/** A protocol version whose contract files the site renders. */
export type ProtocolVersion = (typeof protocolVersions)[number];

/** A file in a protocol version's directory that the site reads. */
export type ProtocolFile = 'openapi.yaml' | 'registry.yaml' | 'registry.schema.json';

/**
 * The statuses a contract's file states: a draft may still change in any way, and a released
 * contract changes only as its freeze allows. A protocol version's `registry.yaml` states its
 * status, and the connector API's file its own.
 */
export const contractStatuses = ['draft', 'released'] as const;

/** A status a contract's file states. */
export type ContractStatus = (typeof contractStatuses)[number];

/** The connector API's file, which the site reads, by its path in the repository. */
export const connectorApiFilePath = 'protocol/connector-api/connector-api.schema.json';

/**
 * The slug of the connector API's reference: its overview page's, and the directory that holds its
 * other pages, without the site's base path.
 */
export const connectorApiSlug = 'reference/connector-api';

/**
 * The directories under which the contract's files sit: the protocol's, and the conformance case
 * list's, which is frozen with each protocol version.
 */
export const contractDirectories = ['protocol/', 'conformance/cases/'] as const;

/**
 * A document of the spec that a conformance case cites: a protocol version's specification, or the
 * connector API's reference. A citation names a document rather than a page, so the document's
 * pages may split or move without changing the cases that cite them.
 */
export type SpecDocument = `protocol-${ProtocolVersion}` | 'connector-api';

/** Every document of the spec, each protocol version's in order, then the connector API's. */
export const specDocuments: readonly SpecDocument[] = [
	...protocolVersions.map((version) => specDocumentOf(version)),
	'connector-api',
];

/**
 * Names a contract file by its path in the repository, as readers and links see it.
 *
 * @param version - The protocol version.
 * @param file - The file in that version's directory.
 * @returns A path such as `protocol/v1/openapi.yaml`.
 */
export function protocolFilePath(version: ProtocolVersion, file: ProtocolFile): string {
	return `protocol/${version}/${file}`;
}

/**
 * Locates a contract file on disk, for the build to read.
 *
 * @param version - The protocol version.
 * @param file - The file in that version's directory.
 * @returns The file's URL.
 */
export function protocolFileUrl(version: ProtocolVersion, file: ProtocolFile): URL {
	return repositoryFileUrl(protocolFilePath(version, file));
}

/**
 * Links to a contract file on GitHub, as `main` holds it.
 *
 * @param version - The protocol version.
 * @param file - The file in that version's directory.
 * @returns The file's URL on GitHub.
 */
export function protocolFileOnGitHub(version: ProtocolVersion, file: ProtocolFile): string {
	return contractPathOnGitHub(protocolFilePath(version, file));
}

/**
 * Links to a file or a directory of the contract on GitHub, as `main` holds it.
 *
 * @param path - The path from the repository's root, such as `protocol/v1/vectors/`, under one of
 *   the contract's directories. A directory's path ends in a slash.
 * @returns The URL of the file's or the directory's page on GitHub.
 * @throws An `Error` that names the path when it isn't under one of the contract's directories.
 */
export function contractPathOnGitHub(path: string): string {
	if (!contractDirectories.some((directory) => path.startsWith(directory))) {
		throw new Error(`${path} is not a path under ${contractDirectories.join(' or ')}.`);
	}
	const kind = path.endsWith('/') ? 'tree' : 'blob';
	return `${repositoryUrl}/${kind}/main/${path.replace(/\/$/, '')}`;
}

/**
 * Locates the connector API's file on disk, for the build to read.
 *
 * @returns The file's URL.
 */
export function connectorApiFileUrl(): URL {
	return repositoryFileUrl(connectorApiFilePath);
}

/**
 * Names the slug of a protocol version's specification: its overview page's, and the directory that
 * holds its other pages and the route pages starlight-openapi generates.
 *
 * @param version - The protocol version.
 * @returns A slug such as `reference/protocol-v1`, without the site's base path.
 */
export function protocolSpecSlug(version: ProtocolVersion): string {
	return `reference/protocol-${version}`;
}

/**
 * Names the slug under which starlight-openapi generates a page for each of a protocol version's
 * reserved routes.
 *
 * @param version - The protocol version.
 * @returns A slug such as `reference/protocol-v1/routes`, without the site's base path.
 */
export function protocolRoutesSlug(version: ProtocolVersion): string {
	return `${protocolSpecSlug(version)}/routes`;
}

/**
 * Names the slug of the page starlight-openapi generates for one reserved route, which it names
 * after the route's `operationId`.
 *
 * @param version - The protocol version.
 * @param operationId - The route's `operationId` in the version's `openapi.yaml`.
 * @returns A slug such as `reference/protocol-v1/routes/operations/hello`, without the site's
 *   base path.
 */
export function protocolRouteSlug(version: ProtocolVersion, operationId: string): string {
	// The plugin slugifies the ID, which leaves the protocol's lowercase IDs as they are; the
	// built-site link check fails on a link to a page it didn't generate.
	return `${protocolRoutesSlug(version)}/operations/${operationId}`;
}

/**
 * Names the document of a protocol version's specification, as a conformance case cites it.
 *
 * @param version - The protocol version.
 * @returns A document such as `protocol-v1`.
 */
export function specDocumentOf(version: ProtocolVersion): SpecDocument {
	return `protocol-${version}`;
}

/**
 * Finds the protocol version whose specification a document is.
 *
 * @param document - The document.
 * @returns The version, or `undefined` for the connector API's reference.
 */
export function protocolVersionOfDocument(document: SpecDocument): ProtocolVersion | undefined {
	return protocolVersions.find((version) => specDocumentOf(version) === document);
}

/**
 * Names the slug of a document: its overview page's, and the directory that holds its other pages.
 *
 * @param document - The document.
 * @returns A slug such as `reference/protocol-v1`, without the site's base path.
 */
export function specDocumentSlug(document: SpecDocument): string {
	const version = protocolVersionOfDocument(document);
	return version === undefined ? connectorApiSlug : protocolSpecSlug(version);
}

/**
 * Locates a file of the repository on disk, for the build to read.
 *
 * @param path - The path from the repository's root.
 * @returns The file's URL.
 */
export function repositoryFileUrl(path: string): URL {
	return new URL(`../../${path}`, import.meta.url);
}

/**
 * Finds the document a page belongs to: the document's overview, a page in its directory, or for a
 * protocol version, a route page starlight-openapi generates there.
 *
 * @param id - The page's ID, which is its slug without the site's base path.
 * @returns The document, or `undefined` for a page outside every document's directory.
 */
export function specDocumentOfPage(id: string): SpecDocument | undefined {
	return specDocuments.find((document) => {
		const slug = specDocumentSlug(document);
		return id === slug || id.startsWith(`${slug}/`);
	});
}

/**
 * Finds the protocol version a page belongs to, as {@link specDocumentOfPage} finds its document.
 *
 * @param id - The page's ID, which is its slug without the site's base path.
 * @returns The version, or `undefined` for a page outside every version's directory.
 */
export function protocolVersionOfPage(id: string): ProtocolVersion | undefined {
	const document = specDocumentOfPage(id);
	return document === undefined ? undefined : protocolVersionOfDocument(document);
}
