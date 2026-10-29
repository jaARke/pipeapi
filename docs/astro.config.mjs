// @ts-check
import { fileURLToPath } from 'node:url';
import starlight from '@astrojs/starlight';
import { defineConfig } from 'astro/config';
import starlightLinksValidator from 'starlight-links-validator';
import starlightOpenAPI, { createOpenAPISidebarGroup } from 'starlight-openapi';
import {
	connectorApiSlug,
	protocolFileUrl,
	protocolRoutesSlug,
	protocolSpecSlug,
	protocolVersions,
	repositoryUrl,
} from './src/protocol.ts';

// The URL the site is published at; Astro takes its origin and its path as two options. Links
// between pages start with its path, and the built-site and site-links checks in justfile hold it
// too.
const siteUrl = new URL('https://jaarke.github.io/pipeapi/');

// Each protocol version, with the sidebar group that starlight-openapi fills with its route pages.
const versions = protocolVersions.map((version) => ({
	version,
	routes: createOpenAPISidebarGroup(),
}));

export default defineConfig({
	site: siteUrl.origin,
	base: siteUrl.pathname,
	logger: { entrypoint: './fail-on-warning.mjs' },
	// Pages the site published at another URL. Astro writes a destination into its redirect page as
	// it is, so the destination carries the base path.
	redirects: {
		[`/${protocolRoutesSlug('v1')}/operations/tags/reserved`]: `${siteUrl.pathname}${protocolRoutesSlug('v1')}/`,
	},
	integrations: [
		starlight({
			title: 'pipeapi',
			description:
				'Talk to an on-device FastAPI backend over a named pipe, a Unix domain socket or a token-protected loopback port.',
			social: [{ icon: 'github', label: 'GitHub', href: repositoryUrl }],
			// A section's overview, then a group for each document: the connector API, then each protocol
			// version, newest first, ending with its route pages. A group autogenerates one directory,
			// in the order its pages' frontmatter gives, and docs/src/routeData.ts checks the labels.
			sidebar: [
				{
					label: 'Reference',
					items: [
						'reference',
						{ label: 'Connector API', items: [{ autogenerate: { directory: connectorApiSlug } }] },
						...versions.toReversed().map(({ version, routes }) => ({
							label: `Protocol ${version}`,
							items: [{ autogenerate: { directory: protocolSpecSlug(version) } }, routes],
						})),
					],
				},
			],
			routeMiddleware: './src/routeData.ts',
			plugins: [
				// A page for each reserved route, generated from each version's openapi.yaml. The routes
				// answer only on a pipeapi endpoint, so the pages show no generated request code, and only
				// the examples the document gives.
				starlightOpenAPI(
					versions.map(({ version, routes }) => ({
						base: protocolRoutesSlug(version),
						schema: fileURLToPath(protocolFileUrl(version, 'openapi.yaml')),
						sidebar: { group: routes, operations: { badges: true } },
						snippets: { operation: false, requestBody: false, response: false },
					}))
				),
				// The validator knows only content pages, so links into the generated pages are left to
				// the built-site check in justfile.
				starlightLinksValidator({
					exclude: protocolVersions.map(
						(version) => `${siteUrl.pathname}${protocolRoutesSlug(version)}/**`
					),
				}),
			],
		}),
	],
});
