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
	return new URL(`../../${protocolFilePath(version, file)}`, import.meta.url);
}

/**
 * Links to a contract file on GitHub, as `main` holds it.
 *
 * @param version - The protocol version.
 * @param file - The file in that version's directory.
 * @returns The file's URL on GitHub.
 */
export function protocolFileOnGitHub(version: ProtocolVersion, file: ProtocolFile): string {
	return `${repositoryUrl}/blob/main/${protocolFilePath(version, file)}`;
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
