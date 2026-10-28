// @ts-check
import { fileURLToPath } from 'node:url';
import js from '@eslint/js';
import astro from 'eslint-plugin-astro';
import n from 'eslint-plugin-n';
import perfectionist from 'eslint-plugin-perfectionist';
import { defineConfig, includeIgnoreFile } from 'eslint/config';
import globals from 'globals';
import tseslint from 'typescript-eslint';

export default defineConfig([
	includeIgnoreFile(fileURLToPath(new URL('.gitignore', import.meta.url))),
	js.configs.recommended,
	tseslint.configs.strictTypeChecked,
	tseslint.configs.stylisticTypeChecked,
	astro.configs.recommended,
	{
		languageOptions: {
			parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
		},
	},
	{
		files: ['**/*.astro'],
		languageOptions: {
			// astro-eslint-parser types a component through a .tsx copy, which it supports only with
			// a tsconfig named outright.
			parserOptions: {
				parser: tseslint.parser,
				extraFileExtensions: ['.astro'],
				projectService: false,
				project: './tsconfig.json',
			},
		},
	},
	{
		// Node runs these: the site's configuration and the build's logger.
		files: ['**/*.mjs'],
		languageOptions: { globals: globals.node },
	},
	{
		plugins: { n, perfectionist },
		rules: {
			// npm hoists every package into node_modules, so an undeclared one still resolves.
			'n/no-extraneous-import': 'error',
			'n/prefer-node-protocol': 'error',
			'perfectionist/sort-imports': [
				'error',
				{
					type: 'alphabetical',
					groups: ['builtin', 'external', 'internal', ['parent', 'sibling', 'index']],
					newlinesBetween: 0,
					// A comment ends a run of sorted imports, so a file's header comment stays at the top.
					partitionByComment: true,
				},
			],
			'perfectionist/sort-named-imports': [
				'error',
				{ type: 'alphabetical', groups: ['value-import', 'type-import'], ignoreAlias: true },
			],
		},
	},
]);
