import { docsLoader } from '@astrojs/starlight/loaders';
import { docsSchema } from '@astrojs/starlight/schema';
import { defineCollection } from 'astro:content';
import { z } from 'astro/zod';
import { conformanceCases, conformanceComponents } from './loaders/conformance';
import { connectorApi, openApi, registry } from './loaders/protocol';

// Each protocol version's contract files load from protocol/ into collections whose names start
// with the version, and the connector API's file into a collection of its own, which the
// components in components/protocol/ read. The conformance case list and its components load from
// conformance/cases/, for the components in components/conformance/.
export const collections = {
	docs: defineCollection({
		loader: docsLoader(),
		schema: docsSchema({
			extend: z.object({
				heading: z
					.boolean()
					.default(false)
					.describe(
						"Whether the page's title is one of its document's headings, as for a page of the spec that holds one section and is titled by its heading. A citation of the document then names the page by its file's name."
					),
			}),
		}),
	}),
	v1Registry: defineCollection({ loader: registry('v1') }),
	v1OpenApi: defineCollection({ loader: openApi('v1') }),
	connectorApi: defineCollection({ loader: connectorApi() }),
	conformanceCases: defineCollection({ loader: conformanceCases() }),
	conformanceComponents: defineCollection({ loader: conformanceComponents() }),
};
