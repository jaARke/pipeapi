import { docsLoader } from '@astrojs/starlight/loaders';
import { docsSchema } from '@astrojs/starlight/schema';
import { defineCollection } from 'astro:content';
import { connectorApi, openApi, registry } from './loaders/protocol';

// Each protocol version's contract files load from protocol/ into collections whose names start
// with the version, and the connector API's file into a collection of its own, which the
// components in components/protocol/ read.
export const collections = {
	docs: defineCollection({ loader: docsLoader(), schema: docsSchema() }),
	v1Registry: defineCollection({ loader: registry('v1') }),
	v1OpenApi: defineCollection({ loader: openApi('v1') }),
	connectorApi: defineCollection({ loader: connectorApi() }),
};
