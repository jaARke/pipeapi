/** The repository the site documents, whose `main` branch holds the contract files. */
export const repositoryUrl = 'https://github.com/jaARke/pipeapi';

/** The protocol versions whose contract files the site renders, each a directory of `protocol/`. */
export const protocolVersions = ['v1'] as const;

/** A protocol version whose contract files the site renders. */
export type ProtocolVersion = (typeof protocolVersions)[number];

/**
 * The protocol versions still in draft, whose pages carry a draft banner. `protocol/README.md`
 * states each version's draft status too, and changes with this list.
 */
export const draftProtocolVersions: readonly ProtocolVersion[] = ['v1'];

/** A file in a protocol version's directory that the site reads. */
export type ProtocolFile = 'openapi.yaml' | 'registry.yaml' | 'registry.schema.json';

/**
 * Whether a contract is a draft, which may still change in any way, or released, which changes only
 * as its freeze allows.
 */
export type ContractStatus = 'draft' | 'released';

/**
 * The connector API's status, which its page shows with a draft banner while it is a draft.
 * `protocol/README.md` states the connector API's status too, and changes with this value.
 */
export const connectorApiStatus: ContractStatus = 'draft';

/** The connector API's file, which the site reads, by its path in the repository. */
export const connectorApiFilePath = 'protocol/connector-api/connector-api.schema.json';

/** The slug of the connector API's page, without the site's base path. */
export const connectorApiPageSlug = 'reference/connector-api';

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
 * Links to a file or a directory under `protocol/` on GitHub, as `main` holds it.
 *
 * @param path - The path from the repository's root, such as `protocol/v1/vectors/`. A
 *   directory's path ends in a slash.
 * @returns The URL of the file's or the directory's page on GitHub.
 * @throws An `Error` that names the path when it isn't under `protocol/`.
 */
export function contractPathOnGitHub(path: string): string {
	if (!path.startsWith('protocol/')) {
		throw new Error(`${path} is not a path under protocol/.`);
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
 * Names the slug of a protocol version's page, under which its generated route pages sit too.
 *
 * @param version - The protocol version.
 * @returns A slug such as `reference/protocol-v1`, without the site's base path.
 */
export function protocolPageSlug(version: ProtocolVersion): string {
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
	return `${protocolPageSlug(version)}/routes`;
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
 * Finds the protocol version a page belongs to: the version's own page, or a route page
 * starlight-openapi generates under it.
 *
 * @param id - The page's ID, which is its slug without the site's base path.
 * @returns The version, or `undefined` for a page outside every version's pages.
 */
export function protocolVersionOfPage(id: string): ProtocolVersion | undefined {
	return protocolVersions.find((version) => {
		const slug = protocolPageSlug(version);
		return id === slug || id.startsWith(`${slug}/`);
	});
}

function repositoryFileUrl(path: string): URL {
	return new URL(`../../${path}`, import.meta.url);
}
