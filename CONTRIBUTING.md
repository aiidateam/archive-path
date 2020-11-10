# Development Conventions

Welcome to the archive-path!
We're excited you're here and want to contribute 🎉.

This page outlines conventions and best practices for development and maintenance of the package.

## Testing

This package utilises [flit](https://flit.readthedocs.io) as the build engine, and [tox](https://tox.readthedocs.io) for test automation.

To install these development dependencies:

```bash
pip install tox
```

To run the tests:

```bash
tox
```

and with test coverage:

```bash
tox -e py37-cov
```

The easiest way to write tests, is to edit tests/fixtures.md

To run the code formatting and style checks:

```bash
tox -e py37-pre-commit
```

or directly

```bash
pip install pre-commit
pre-commit run --all
```

## PRs and commits

All code changes to the code should be made *via* PRs to the `main` branch.

There are three ways of 'merging' pull requests on GitHub.
**Squash and merge** is the favoured method, applicable to the majority of PRs.

A commit:

- should ideally address one issue
- should be a self-contained change to the code base
- must not lump together unrelated changes

Repositories should follow the following convention (where possible):

```md
<EMOJI> <KEYWORD>: Summarize changes in 72 characters or less (#<PR number>)

More detailed explanatory text, if necessary.
The blank line separating the summary from the body is
critical (unless you omit the body entirely); various tools like `log`,
`shortlog` and `rebase` can get confused if you run the two together.

Explain the problem that this commit is solving. Focus on why you are
making this change as opposed to how (the code explains that).  Are
there side effects or other unintuitive consequences of this change?
Here's the place to explain them to someone else reading your message in
the future. Make sure to include some necessary context for difficult
concepts that might change in the future.

There is no need to mention you also added unit tests when adding a new feature. The code diff already makes this clear.
```

Keywords/emojis are adapted from [Emoji-Log](https://github.com/ahmadawais/Emoji-Log) and [gitmoji](https://github.com/carloscuesta/gitmoji) and should be one of the following (brackets contain [GitHub emoji markup](https://gist.github.com/rxaviers/7360908) for reference):

- `‼️ BREAKING:` (`:bangbang:`) — to introduce a back-incompatible change(s) (and/or remove deprecated code).
- `✨ NEW:` (`:sparkles:`) — to introduce a new feature(s).
- `👌 IMPROVE:` (`:ok_hand:`) — to improve an existing code/feature (with no breaking changes).
- `🐛 FIX:` (`:bug:`) — to fix a code bug.
- `📚 DOCS:` (`:books:`) — to add new documentation.
- `🔧 MAINTAIN:` (`:wrench:`) — to make minor changes (like fixing typos) which should not appear in a changelog.
- `🧪 TEST:` (`:testube:`) — to add additional testing only.
- `🚀 RELEASE:` (`:rocket:`) — to bump the package version for release.
- `⬆️ UPGRADE:` (`:arrow_up:`) — for upgrading a dependency pinning.
- `♻️ REFACTOR:` (`:recycle:`) — for refactoring existing code (with no specific improvements).
- `🗑️ DEPRECATE:` (`:wastebasket:`) — mark some code as deprecated (for removal in a later release). The future version when it will be removed should also be specified, and (if applicable) what will replace it.
- `🔀 MERGE:` (`:twisted_rightwards_arrows:`) — for a merge commit (then all commits within the merge should be categorised)
- `❓ OTHER:` (`:question:`) — anything not covered above (use as a last resort!).

## The process of creating a release

Below is the full workflow for creating a release:

- Make a release commit `🚀 RELEASE: ...` on `main` (*via* PR) which bumps the `__version__` to `M.m.p` and adds a section to `CHANGELOG.md` with the version, date and details of the changes.
- Create a GitHub release for that commit, with tag `vM.m.p`, heading `vM.m.p`.
- Check that automated release workflows complete successfully.
