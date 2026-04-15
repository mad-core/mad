# Releasing `mad` to PyPI

`mad` is published to PyPI through an automated GitHub Actions pipeline modelled
on the changesets + npm flow used in `angi`. Versioning is driven by
[python-semantic-release](https://python-semantic-release.readthedocs.io/) from
the Conventional Commits history, and publishing uses
[PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/) (OIDC) —
no long-lived API tokens are stored in the repo.

## Release pipeline

```
push to main
    │
    ▼
┌───────────────────────────┐
│ release  (release.yml)    │  pytest → semantic-release → upload dist/
└───────────┬───────────────┘
            │ outputs.released == true
            ▼
┌───────────────────────────┐
│ publish-testpypi          │  pypa/gh-action-pypi-publish → test.pypi.org
└───────────┬───────────────┘
            ▼
┌───────────────────────────┐
│ publish-pypi              │  pypa/gh-action-pypi-publish → pypi.org
└───────────────────────────┘
```

The `release` job is a no-op when the commits since the last tag do not require
a version bump, exactly like `changesets/action` is a no-op without pending
changesets.

## Commit → version bump rules

`commit_parser = "conventional"` in `pyproject.toml`. Current bump table:

| Commit prefix                                 | Bump    |
| --------------------------------------------- | ------- |
| `fix: …`                                      | patch   |
| `feat: …`                                     | minor   |
| `feat!: …` / footer `BREAKING CHANGE: …`      | minor while `0.x` (`major_on_zero = false`), major from `1.0.0` onwards |
| `chore:`, `docs:`, `refactor:`, `test:`, …    | no release |

The `commit_message` template already includes the Claude Co-Authored-By
trailer required by the project commit policy.

Preview the next version locally without pushing:

```bash
semantic-release version --print
```

## One-time operator setup

### 1. GitHub environments

In the repo settings → Environments, create two environments:

- `testpypi`
- `pypi` (optionally require manual review before deployment)

### 2. PyPI trusted publishers

Register the publisher **before** the first release. PyPI lets you create a
"pending publisher" even when the project name does not exist yet.

**TestPyPI** — https://test.pypi.org/manage/account/publishing/

| Field              | Value         |
| ------------------ | ------------- |
| PyPI project name  | `mad`         |
| Owner              | `jlsaco`      |
| Repository name    | `mad`         |
| Workflow filename  | `release.yml` |
| Environment name   | `testpypi`    |

**PyPI** — https://pypi.org/manage/account/publishing/ with environment `pypi`.

### 3. GitHub Actions permissions

The workflow requests `id-token: write` only inside the `publish-*` jobs. No
changes to default `GITHUB_TOKEN` permissions are required beyond that.

## Local sanity checks

```bash
make install                 # venv + pip install -e '.[dev]'
make test                    # pytest -q
make build                   # python -m build → dist/*.whl, dist/*.tar.gz
python -m twine check dist/* # PyPI metadata sanity

# Verify the wheel installs clean and the console script works.
python -m venv /tmp/mad-smoke && /tmp/mad-smoke/bin/pip install dist/mad-*.whl
/tmp/mad-smoke/bin/mad --help
```

## Troubleshooting

- **`release` job says "No release will be made"** — there are no
  `feat:`/`fix:` commits since the last tag. Expected, not an error.
- **`publish-*` fails with `invalid-publisher`** — the trusted publisher on
  PyPI/TestPyPI does not match `owner/repo/workflow/environment`. Recheck the
  four fields in the PyPI publisher settings.
- **semantic-release pushes the version commit but publish is skipped** — the
  job only runs when `steps.semrel.outputs.released == 'true'`. Inspect the
  action logs to see which commit types it considered.
- **Wrong version in the wheel** — `version_toml` and `version_variables` must
  both point at live files. `pyproject.toml:project.version` and
  `src/mad/__init__.py:__version__` are the single source of truth.
