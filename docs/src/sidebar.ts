import type { StarlightRouteData } from '@astrojs/starlight/route-data';
import { getEntry } from 'astro:content';
import {
	documentStatus,
	openApiDocument,
	pageHref,
	pageIdOf,
} from './components/protocol/contract';
import {
	protocolRoutesSlug,
	protocolVersionOfPage,
	protocolVersions,
	specDocuments,
	specDocumentSlug,
} from './protocol';

/** An entry of a page's sidebar: a link, or a group of entries. */
export type SidebarEntry = StarlightRouteData['sidebar'][number];

/** One card of an index page: a page, or a group by its first page. */
export interface IndexCard {
	readonly title: string;
	readonly href: string;
	readonly description: string;
}

/**
 * Replaces the tag level in each protocol version's routes group with its routes, and labels the
 * group with the tag's summary. starlight-openapi nests a group for each tag, labeled with the
 * tag's name, which is an identifier, and every reserved route has the one tag.
 *
 * @param sidebar - A page's sidebar, after starlight-openapi's middleware has added the routes.
 * @throws An `Error` that names the version when its routes group isn't in the sidebar once, or
 *   doesn't hold exactly one tag's group, the one tag its `openapi.yaml` declares.
 */
export async function flattenRouteGroups(sidebar: readonly SidebarEntry[]): Promise<void> {
	for (const version of protocolVersions) {
		const group = onlyGroupStartingAt(sidebar, protocolRoutesSlug(version));
		const { tags } = await openApiDocument(version);
		const tagGroups = group.entries.filter((entry) => entry.type === 'group');
		const [tag] = tags;
		const [tagGroup] = tagGroups;
		if (tag === undefined || tagGroup === undefined || tags.length > 1 || tagGroups.length > 1) {
			throw new Error(
				`Protocol ${version}'s routes group holds ${String(tagGroups.length)} groups for tags, and its openapi.yaml declares ${String(tags.length)} tags. The sidebar leaves the tag level out only when every route has the one tag.`
			);
		}
		if (tagGroup.label !== tag.name) {
			throw new Error(
				`Protocol ${version}'s routes group holds a group labeled ${tagGroup.label}, not its tag's name, ${tag.name}.`
			);
		}
		group.label = tag.summary;
		group.entries = group.entries.flatMap((entry) =>
			entry.type === 'group' ? entry.entries : [entry]
		);
	}
}

/**
 * Gives the group of each document of the spec whose contract is a draft a badge saying so.
 *
 * @param sidebar - A page's sidebar.
 * @throws An `Error` that names the document when no group, or more than one, starts at its
 *   overview page.
 */
export async function markDraftDocuments(sidebar: readonly SidebarEntry[]): Promise<void> {
	for (const document of specDocuments) {
		if ((await documentStatus(document)) === 'draft') {
			onlyGroupStartingAt(sidebar, specDocumentSlug(document)).badge = {
				text: 'Draft',
				variant: 'caution',
			};
		}
	}
}

/**
 * Checks the sidebar's labels against the rule `docs/contributing/guide-site.md`'s "Sections"
 * states: no label starts with a lowercase letter, no group holds two entries with the same label,
 * and no entry repeats its group's label.
 *
 * @param sidebar - A page's sidebar, after every change the middleware makes.
 * @throws An `Error` that names the label and the groups that hold it, on the first that breaks
 *   the rule.
 */
export function checkLabels(sidebar: readonly SidebarEntry[]): void {
	checkEntries(sidebar, []);
}

/**
 * Lists the cards of an index page: every other entry of the sidebar's group that holds the page,
 * each described by its page's description, or for a group, by its first page's.
 *
 * @param sidebar - The index page's sidebar.
 * @returns The cards, in the sidebar's order.
 * @throws An `Error` when no group holds the current page, or an entry's page has no description.
 */
export async function indexCards(sidebar: readonly SidebarEntry[]): Promise<readonly IndexCard[]> {
	const group = groupHoldingCurrent(sidebar);
	if (group === undefined) {
		throw new Error('No group of the sidebar holds the index page.');
	}
	const cards: IndexCard[] = [];
	for (const entry of group.entries) {
		if (entry.type === 'link' && entry.isCurrent) {
			continue;
		}
		const href = entry.type === 'link' ? entry.href : firstLinkOf(entry)?.href;
		if (href === undefined) {
			throw new Error(`The sidebar's group ${entry.label} holds no page.`);
		}
		cards.push({ title: entry.label, href, description: await descriptionOf(href) });
	}
	return cards;
}

type SidebarGroup = Extract<SidebarEntry, { type: 'group' }>;

type SidebarLink = Extract<SidebarEntry, { type: 'link' }>;

function checkEntries(entries: readonly SidebarEntry[], parents: readonly string[]): void {
	const seen = new Set<string>();
	const parent = parents.at(-1);
	for (const entry of entries) {
		const { label } = entry;
		const where = [...parents, label].join(' > ');
		if (/^\p{Ll}/u.test(label)) {
			throw new Error(`The sidebar's label ${where} starts with a lowercase letter.`);
		}
		const key = label.toLocaleLowerCase('en');
		if (seen.has(key)) {
			const group = parents.length === 0 ? 'top level' : `group ${parents.join(' > ')}`;
			throw new Error(`The sidebar's ${group} holds two entries labeled ${label}.`);
		}
		seen.add(key);
		if (key === parent?.toLocaleLowerCase('en')) {
			throw new Error(`The sidebar's entry ${where} repeats its group's label.`);
		}
		if (entry.type === 'group') {
			checkEntries(entry.entries, [...parents, label]);
		}
	}
}

// The one group whose first entry links a page, as a document's group starts at its overview.
function onlyGroupStartingAt(sidebar: readonly SidebarEntry[], slug: string): SidebarGroup {
	const href = pageHref(slug);
	const groups = groupsOf(sidebar).filter(
		({ entries: [first] }) => first?.type === 'link' && first.href === href
	);
	const [group] = groups;
	if (group === undefined || groups.length > 1) {
		throw new Error(
			`The sidebar has ${String(groups.length)} groups that start at ${href}, where one should.`
		);
	}
	return group;
}

function groupsOf(entries: readonly SidebarEntry[]): readonly SidebarGroup[] {
	return entries.flatMap((entry) =>
		entry.type === 'group' ? [entry, ...groupsOf(entry.entries)] : []
	);
}

function groupHoldingCurrent(entries: readonly SidebarEntry[]): SidebarGroup | undefined {
	return groupsOf(entries).find((group) =>
		group.entries.some((entry) => entry.type === 'link' && entry.isCurrent)
	);
}

function firstLinkOf(group: SidebarGroup): SidebarLink | undefined {
	for (const entry of group.entries) {
		const link = entry.type === 'link' ? entry : firstLinkOf(entry);
		if (link !== undefined) {
			return link;
		}
	}
	return undefined;
}

// A page's description, or for a version's routes overview, which starlight-openapi generates,
// its OpenAPI document's summary.
async function descriptionOf(href: string): Promise<string> {
	const id = pageIdOf(href);
	if (id === undefined) {
		throw new Error(`An index page's card links ${href}, outside the site.`);
	}
	const version = protocolVersionOfPage(id);
	if (version !== undefined && id === protocolRoutesSlug(version)) {
		return (await openApiDocument(version)).summary;
	}
	const description = (await getEntry('docs', id))?.data.description;
	if (description === undefined) {
		throw new Error(`The page ${href} has no description for an index page's card.`);
	}
	return description;
}
