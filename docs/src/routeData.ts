import { defineRouteMiddleware } from '@astrojs/starlight/route-data';
import { draftProtocolVersions, protocolPageSlug } from './protocol';

// A draft protocol version's page and the route pages starlight-openapi generates under it carry
// a banner. The plugin's pages have no frontmatter, so the banner is set here for all of them.
export const onRequest = defineRouteMiddleware((context) => {
	const route = context.locals.starlightRoute;
	const isDraft = draftProtocolVersions.some((version) => {
		const slug = protocolPageSlug(version);
		return route.id === slug || route.id.startsWith(`${slug}/`);
	});
	if (isDraft) {
		route.entry.data.banner = { content: 'This page is a draft.' };
	}
});
