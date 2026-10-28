// @ts-check
import { fileURLToPath } from 'node:url';
import starlight from '@astrojs/starlight';
import { defineConfig } from 'astro/config';
import starlightLinksValidator from 'starlight-links-validator';
import starlightOpenAPI, { openAPISidebarGroups } from 'starlight-openapi';
import {
	protocolFileUrl,
	protocolRoutesSlug,
	protocolVersions,
	repositoryUrl,
} from './src/protocol.ts';

// The URL the site is published at; Astro takes its origin and its path as two options. Links
// between pages start with its path, and the built-site link check in justfile holds it too.
const siteUrl = new URL('https://jaarke.github.io/pipeapi/');

export default defineConfig({
	site: siteUrl.origin,
	base: siteUrl.pathname,
	logger: { entrypoint: './fail-on-warning.mjs' },
	integrations: [
		starlight({
			title: 'pipeapi',
			description:
				'Talk to an on-device FastAPI backend over a named pipe, a Unix domain socket or a token-protected loopback port.',
			social: [{ icon: 'github', label: 'GitHub', href: repositoryUrl }],
			sidebar: [
				{
					label: 'Reference',
					items: [{ autogenerate: { directory: 'reference' } }, ...openAPISidebarGroups],
				},
			],
			routeMiddleware: './src/routeData.ts',
			plugins: [
				// A page for each reserved route, generated from each version's openapi.yaml. The routes
				// answer only on a pipeapi endpoint, so the pages show no generated request code, and only
				// the examples the document gives.
				starlightOpenAPI(
					protocolVersions.map((version) => ({
						base: protocolRoutesSlug(version),
						schema: fileURLToPath(protocolFileUrl(version, 'openapi.yaml')),
						sidebar: { label: `Protocol ${version} routes` },
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
