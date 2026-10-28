# The documentation system

pipeapi's documentation has two audiences. People building an app with pipeapi read the user documentation: each package's README, each package's API reference and the guide site. People changing pipeapi read the contributor documentation: [CONTRIBUTING.md](../../CONTRIBUTING.md) and the pages in this folder. This page says where each kind of page goes, which file or page owns each fact, what a contributor page holds, and how to mark unreleased behavior. [The guide site](guide-site.md) says how the site is organized, built and checked, and why.

## Where each kind of documentation goes

| Kind | Reader | Lives in | Holds |
| --- | --- | --- | --- |
| Package README | Someone choosing or installing a package | The package's directory; its registry (PyPI, npm, NuGet, crates.io, pkg.go.dev) shows it | What the package is, how to install it, a minimal connect-and-call example, and links to the guide site and the package's API reference |
| API reference | Someone calling a symbol | Doc comments in the package's source, rendered by its ecosystem's own tool where its users look for it (docs.rs, pkg.go.dev, editor hovers or the guide site) | Every public symbol |
| Guide site | Someone building an app, in any language | `docs/src/content/docs/`, in the [section](guide-site.md#sections) its job decides | Everything else a user needs |
| Contributor pages | Someone changing pipeapi | `docs/contributing/` | How each part is built and checked, its conventions, and why its design is what it is |

The first three are the user documentation's layers, each with one job. One guide site serves every language, so a user never needs five sites, and per-symbol detail stays in the doc comments, where the code and its description change together.

## Which file or page owns each fact

Each fact has one owner, and every other page links to it rather than restating it.

| Fact | Owner |
| --- | --- |
| The protocol's names, values, routes and shapes | The files in `protocol/`, which the site [renders](guide-site.md#how-the-contract-renders); [protocol/README.md](../../protocol/README.md) says which file owns what |
| How to change the contract | [protocol/README.md](../../protocol/README.md) |
| What a public symbol does | Its doc comment; READMEs and guide pages link the API reference |
| How to do a task with pipeapi, and the concepts behind it | The guide site; the API reference links it for concepts |
| A setting's value and its reason | The file that holds the setting, with the reason in a comment beside it; pages link the file rather than restating the value |
| What a command does | Its recipe's comment in its justfile, which `just` lists; CONTRIBUTING.md's [commands](../../CONTRIBUTING.md#commands) summarize the everyday ones |
| What each check needs installed | CONTRIBUTING.md's [prerequisites](../../CONTRIBUTING.md#prerequisites) |
| A component's guarantees, the reasons for its design and what was rejected | The component's page in this folder |
| Work not yet done, and open design questions | The [issues](https://github.com/jaARke/pipeapi/issues) |

## Unreleased features

The guide site [has one version](guide-site.md#one-unversioned-site), built from the repository rather than from a release, so it can describe behavior that no release includes yet. Mark that behavior with a caution aside titled "Unreleased", directly under the heading of the section that describes it:

```md
:::caution[Unreleased]
No release includes this yet.
:::
```

A page that describes only unreleased behavior carries the aside at its top, and the same marker in the sidebar through its frontmatter:

```yaml
sidebar:
  badge:
    text: Unreleased
    variant: caution
```

The marker comes off once a release includes the feature. While no package has a release, the homepage says so, and pages carry no marker.

## Contributor pages

The pages in this folder are Markdown read on GitHub, beside the code they describe. Each one:

- covers one topic, short enough to read in a few minutes, and is listed in the folder's [index](README.md);
- records, for its component, what it guarantees, why it's built that way and what was rejected, so the closed issue isn't the only record;
- describes what exists, with no history or plans, and changes in the pull request that changes what it describes;
- links each fact's owner, the user documentation included, rather than restating it.

The guide site's content root sits in a directory of its own, so these pages stay out of the site's build and search by construction. They live here rather than elsewhere for these reasons:

- A section of the guide site would mix two audiences.
- The wiki isn't indexed by search engines until a repository has 500 stars, needs a publishing workflow that can write to the repository, and suits a handful of pages rather than a page per component.
