// typescript-eslint reads a component's template as TSX, where Astro declares no element type;
// this one, from eslint-plugin-astro's README, lets its type-aware rules check what a template
// returns.
import 'astro/astro-jsx';

declare global {
	namespace JSX {
		type Element = HTMLElement;
	}
}
