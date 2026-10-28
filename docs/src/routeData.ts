import { defineRouteMiddleware } from '@astrojs/starlight/route-data';
import {
	connectorApiPageSlug,
	connectorApiStatus,
	draftProtocolVersions,
	protocolVersionOfPage,
} from './protocol';

// A draft protocol version's page and the route pages starlight-openapi generates under it carry
// a banner, as does the connector API's page while it is a draft. The plugin's pages have no
// frontmatter, so the banner is set here for all of them, from where each status is stated.
export const onRequest = defineRouteMiddleware((context) => {
	const route = context.locals.starlightRoute;
	const version = protocolVersionOfPage(route.id);
	const draftProtocol = version !== undefined && draftProtocolVersions.includes(version);
	const draftConnectorApi = route.id === connectorApiPageSlug && connectorApiStatus === 'draft';
	if (draftProtocol || draftConnectorApi) {
		route.entry.data.banner = { content: 'This page is a draft.' };
	}
});
