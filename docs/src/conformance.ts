import { protocolSpecSlug } from './protocol';

/** The conformance suite's case list, which the site renders, by its path in the repository. */
export const conformanceCasesFilePath = 'conformance/cases/cases.yaml';

/** The case list's schema, which states the defaults of a case's fields, by its path in the repository. */
export const conformanceCasesSchemaPath = 'conformance/cases/cases.schema.json';

/** The components the conformance cases need, by its path in the repository. */
export const conformanceComponentsFilePath = 'conformance/cases/components.yaml';

/**
 * The slug of the case list's page, without the site's base path. It sits in protocol v1's
 * directory, since the cases are frozen with protocol v1, but is no page of its specification.
 */
export const conformancePageSlug = `${protocolSpecSlug('v1')}/conformance`;
