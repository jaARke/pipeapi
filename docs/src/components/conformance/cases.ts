import { getCollection, getEntry, render, type CollectionEntry } from 'astro:content';
import {
	conformanceCasesFilePath,
	conformanceComponentsFilePath,
	conformancePageSlug,
} from '../../conformance';
import {
	protocolVersionOfDocument,
	specDocuments,
	specDocumentSlug,
	type SpecDocument,
} from '../../protocol';
import { connectorApiRows, pageHref, protocolRows } from '../protocol/contract';

/** The case list, as its collection holds it. */
export type CaseList = CollectionEntry<'conformanceCases'>['data'];

/** One case, with the defaults its schema gives the fields it leaves out. */
export type ConformanceCase = CaseList['areas'][number]['cases'][number];

/** One component the cases need. */
export type Component = CollectionEntry<'conformanceComponents'>['data']['components'][number];

/** An anchor of a document of the spec, which a case may cite. */
export interface DocumentAnchor {
	readonly document: SpecDocument;
	/** A heading's slug, or a table row's name such as `rejections.draining`. */
	readonly anchor: string;
	readonly kind: 'heading' | 'row';
	/** A heading's text, or a row's anchor. */
	readonly text: string;
	readonly href: string;
}

/** One anchor of a document, with the cases and invariants that cover it. */
export interface AnchorCoverage {
	readonly anchor: DocumentAnchor;
	/** The IDs of the cases and invariants that cite it, in the file's order. */
	readonly coveredBy: readonly string[];
	/** Why no case covers it, for an anchor the case list lists as uncovered. */
	readonly reason: string | undefined;
}

/** A document's anchors, each with what covers it. */
export interface DocumentCoverage {
	readonly document: SpecDocument;
	readonly title: string;
	readonly anchors: readonly AnchorCoverage[];
}

// The headings a page's table of contents shows, which are the ones a citation may name.
const headingDepths = { minimum: 2, maximum: 3 } as const;

const anchorsByDocument = new Map<SpecDocument, Promise<readonly DocumentAnchor[]>>();

/**
 * Reads the case list.
 *
 * @returns The areas, each with its cases, the invariants and the uncovered anchors, in the file's
 *   order.
 * @throws An `Error` when the case list didn't load.
 */
export async function caseList(): Promise<CaseList> {
	const entry = await getEntry('conformanceCases', 'case-list');
	if (entry === undefined) {
		throw new Error(`${conformanceCasesFilePath} did not load.`);
	}
	return entry.data;
}

/**
 * Reads the components the cases need.
 *
 * @returns The components, in the file's order.
 * @throws An `Error` when the component table didn't load.
 */
export async function components(): Promise<readonly Component[]> {
	const entry = await getEntry('conformanceComponents', 'components');
	if (entry === undefined) {
		throw new Error(`${conformanceComponentsFilePath} did not load.`);
	}
	return entry.data.components;
}

/**
 * Names a document as its overview page's title names it.
 *
 * @param document - The document.
 * @returns The title, such as `Protocol v1`.
 * @throws An `Error` when the document's overview page doesn't exist.
 */
export async function documentTitle(document: SpecDocument): Promise<string> {
	const slug = specDocumentSlug(document);
	const entry = await getEntry('docs', slug);
	if (entry === undefined) {
		throw new Error(`The page ${slug}, the overview of the document ${document}, doesn't exist.`);
	}
	return entry.data.title;
}

/**
 * Lists every anchor of a document a case may cite, page by page: a page's title, where it is one
 * of the document's headings, named by the page's name in the document's directory, then the
 * headings the page's table of contents shows; then the rows of the tables of the contract its
 * pages render.
 *
 * @param document - The document.
 * @returns The anchors.
 * @throws An `Error` when one of the document's pages or files didn't load.
 */
export function documentAnchors(document: SpecDocument): Promise<readonly DocumentAnchor[]> {
	let anchors = anchorsByDocument.get(document);
	if (anchors === undefined) {
		anchors = readAnchors(document);
		anchorsByDocument.set(document, anchors);
	}
	return anchors;
}

/**
 * Resolves a citation of the case list against the documents of the spec.
 *
 * @param citation - The citation, such as `protocol-v1#rejections.draining`.
 * @param citedBy - The ID of the case or invariant that cites it, or `uncovered`, for errors.
 * @returns The anchor the citation names.
 * @throws An `Error` that names the citation and what cites it when it names no document, or no
 *   anchor of its document, or a heading more than one of the document's pages holds.
 */
export async function resolveCitation(citation: string, citedBy: string): Promise<DocumentAnchor> {
	const cites = `${conformanceCasesFilePath}'s ${citedBy} cites ${citation}`;
	const separator = citation.indexOf('#');
	const named = citation.slice(0, separator);
	const document = specDocuments.find((known) => known === named);
	if (separator < 0 || document === undefined) {
		throw new Error(`${cites}, which names none of the documents ${specDocuments.join(', ')}.`);
	}
	const anchor = citation.slice(separator + 1);
	const found = (await documentAnchors(document)).filter((each) => each.anchor === anchor);
	const [only] = found;
	if (only === undefined || found.length > 1) {
		const which = found.length > 1 ? 'more than one page' : 'no heading or table row';
		throw new Error(`${cites}, which ${which} of ${await documentTitle(document)} holds.`);
	}
	return only;
}

/**
 * Maps every anchor of every document to the cases and invariants that cite it, and checks that
 * the case list explains each anchor none cites.
 *
 * @returns Each document's anchors, with what covers each.
 * @throws An `Error` that lists every citation that doesn't resolve, every anchor that no case or
 *   invariant covers and the case list doesn't list as uncovered, and every anchor it lists as
 *   uncovered that a case or invariant covers.
 */
export async function coverage(): Promise<readonly DocumentCoverage[]> {
	const { areas, invariants, uncovered } = await caseList();
	const citers = [...areas.flatMap(({ cases }) => cases), ...invariants];
	const problems: string[] = [];
	const coveredBy = new Map<string, string[]>();
	for (const { id, covers } of citers) {
		for (const citation of covers) {
			const anchor = await resolved(citation, id, problems);
			if (anchor !== undefined) {
				const key = keyOf(anchor);
				coveredBy.set(key, [...(coveredBy.get(key) ?? []), id]);
			}
		}
	}
	const reasons = new Map<string, string>();
	for (const { citation, reason } of uncovered) {
		const anchor = await resolved(citation, 'uncovered', problems);
		if (anchor !== undefined) {
			reasons.set(keyOf(anchor), reason);
		}
	}
	const documents: DocumentCoverage[] = [];
	for (const document of specDocuments) {
		const title = await documentTitle(document);
		const anchors = (await documentAnchors(document)).map((anchor) => {
			const key = keyOf(anchor);
			const covering = coveredBy.get(key) ?? [];
			const reason = reasons.get(key);
			if (covering.length === 0 && reason === undefined) {
				problems.push(`${key} has no case or invariant, and uncovered doesn't say why.`);
			}
			if (covering.length > 0 && reason !== undefined) {
				problems.push(`uncovered lists ${key}, which ${covering.join(', ')} cover.`);
			}
			return { anchor, coveredBy: covering, reason };
		});
		documents.push({ document, title, anchors });
	}
	if (problems.length > 0) {
		throw new Error(`${conformanceCasesFilePath}'s coverage of the spec:\n${problems.join('\n')}`);
	}
	return documents;
}

async function readAnchors(document: SpecDocument): Promise<readonly DocumentAnchor[]> {
	const anchors: DocumentAnchor[] = [];
	const directory = `${specDocumentSlug(document)}/`;
	for (const page of await documentPages(document)) {
		if (page.data.heading) {
			if (!page.id.startsWith(directory)) {
				throw new Error(
					`The overview ${page.id} sets heading, which only a document's other pages may.`
				);
			}
			const anchor = page.id.slice(directory.length);
			const text = page.data.title;
			anchors.push({ document, anchor, kind: 'heading', text, href: pageHref(page.id) });
		}
		const { headings } = await render(page);
		for (const { depth, slug: anchor, text } of headings) {
			if (depth >= headingDepths.minimum && depth <= headingDepths.maximum) {
				anchors.push({ document, anchor, kind: 'heading', text, href: pageHref(page.id, anchor) });
			}
		}
	}
	const version = protocolVersionOfDocument(document);
	const rows = version === undefined ? await connectorApiRows() : await protocolRows(version);
	for (const { anchor, href } of rows) {
		anchors.push({ document, anchor, kind: 'row', text: anchor, href });
	}
	return anchors;
}

// A document's pages in the sidebar's order: its overview, then each page in its directory but the
// case list's, which renders the cases rather than the spec.
async function documentPages(document: SpecDocument): Promise<readonly CollectionEntry<'docs'>[]> {
	const slug = specDocumentSlug(document);
	const pages = await getCollection(
		'docs',
		({ id }) => (id === slug || id.startsWith(`${slug}/`)) && id !== conformancePageSlug
	);
	if (!pages.some(({ id }) => id === slug)) {
		throw new Error(`The page ${slug}, the overview of the document ${document}, doesn't exist.`);
	}
	// Starlight's sidebar sorts by each page's order, then by ID.
	return pages.toSorted(
		(a, b) =>
			(a.data.sidebar.order ?? Number.MAX_VALUE) - (b.data.sidebar.order ?? Number.MAX_VALUE) ||
			a.id.localeCompare(b.id, 'en')
	);
}

// Resolves a citation, recording why it doesn't resolve rather than stopping at the first.
async function resolved(
	citation: string,
	citedBy: string,
	problems: string[]
): Promise<DocumentAnchor | undefined> {
	try {
		return await resolveCitation(citation, citedBy);
	} catch (error) {
		problems.push(error instanceof Error ? error.message : String(error));
		return undefined;
	}
}

function keyOf(anchor: DocumentAnchor): string {
	return `${anchor.document}#${anchor.anchor}`;
}
