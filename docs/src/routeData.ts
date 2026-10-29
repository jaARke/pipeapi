import { defineRouteMiddleware } from '@astrojs/starlight/route-data';
import { documentStatus } from './components/protocol/contract';
import { specDocumentOfPage } from './protocol';
import { checkLabels, flattenRouteGroups, markDraftDocuments } from './sidebar';

// A draft document's pages carry a banner, the route pages starlight-openapi generates among them,
// and its sidebar group a badge, from the status the contract's file states. The plugin's pages
// have no frontmatter, so the banner is set here for all of them. The sidebar changes wait for the
// plugin's middleware, which adds the route pages to the sidebar after this one runs.
export const onRequest = defineRouteMiddleware(async (context, next) => {
	const route = context.locals.starlightRoute;
	const document = specDocumentOfPage(route.id);
	if (document !== undefined && (await documentStatus(document)) === 'draft') {
		route.entry.data.banner = { content: 'This page is a draft.' };
	}
	await next();
	await flattenRouteGroups(route.sidebar);
	await markDraftDocuments(route.sidebar);
	checkLabels(route.sidebar);
});
