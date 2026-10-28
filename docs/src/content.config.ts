import { docsLoader } from '@astrojs/starlight/loaders';
import { docsSchema } from '@astrojs/starlight/schema';
import { defineCollection } from 'astro:content';
import { openApiSource, registrySection } from './loaders/protocol';

// Each protocol version's contract files load from protocol/ into collections whose names start
// with the version, which the components in components/protocol/ read.
export const collections = {
	docs: defineCollection({ loader: docsLoader(), schema: docsSchema() }),
	v1EnvironmentVariables: defineCollection({
		loader: registrySection('v1', 'environment_variables'),
	}),
	v1Constants: defineCollection({ loader: registrySection('v1', 'constants') }),
	v1OpenApiSource: defineCollection({ loader: openApiSource('v1') }),
};
