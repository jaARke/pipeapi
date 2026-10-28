// @ts-check
// Astro has no option that fails a run on warnings. A log handler sees every message Astro's
// logger handles (Astro's own, Vite's and each integration's), so this one prints them through
// Astro's default handler, counts warnings and errors, and fails the process as it exits. Output
// written to the console directly, such as a console.warn, bypasses the logger and fails nothing.
// Scraping the console output instead would depend on the shell and on the log format.
import { matchesLevel } from 'astro/logger';
import nodeLogger from 'astro/logger/node';

// Starlight looks up an optional i18n collection and an optional custom 404 page, and expects both
// to be missing. It hides the first warning from console.warn, which Astro 7 no longer logs through.
const expectedWarnings = [
	{
		label: 'content',
		message:
			'The collection "i18n" does not exist or is empty. Please check your content config file for errors.',
	},
	{ label: 'content', message: 'Entry docs → 404 was not found.' },
];

// Astro can load this module more than once in one process, so the count lives on globalThis.
const countKey = Symbol.for('pipeapi.docs.failOnWarning.count');

/**
 * Creates a log destination that prints as Astro's default one does and makes the process exit
 * with an error after any warning or error Astro's logger passes it.
 *
 * @returns {import('astro').AstroLoggerDestination}
 */
export default function failOnWarning() {
	const destination = nodeLogger();
	return {
		write(message) {
			if (isExpected(message)) return;
			destination.write(message);
			if (matchesLevel(message.level, 'warn')) recordWarning();
		},
	};
}

/** @param {import('astro').AstroLoggerMessage} message */
function isExpected(message) {
	return expectedWarnings.some(
		({ label, message: text }) =>
			message.level === 'warn' && message.label === label && message.message === text
	);
}

function recordWarning() {
	const store = /** @type {Record<symbol, number | undefined>} */ (globalThis);
	const count = store[countKey];
	if (count === undefined) {
		process.once('exit', () => {
			process.stderr.write(
				`\n${String(store[countKey] ?? 0)} warning or error message(s) above: the docs check treats every warning Astro's logger reports as an error.\n`
			);
			process.exitCode = 1;
		});
	}
	store[countKey] = (count ?? 0) + 1;
}
