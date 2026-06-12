# CI Portability: GitHub Actions ↔ Gitea/Forgejo Actions ↔ GitLab CI

The two host-CI files — `.github/workflows/ci.yml` (test on PR/push) and
`.github/workflows/release.yml` (build + push the pipeline image on `v*` tags) —
are the **intentionally swappable thin layer** of the SDLC. All orchestration
logic lives on the box (LangGraph pipeline) behind the forge protocol; the host
CI only does what any forge's CI does natively: run tests and cut releases.
**Porting cost to a new host = rewriting these 2 files.** Nothing else in the
SDLC references the CI host.

Both files deliberately use only the portable syntax subset: `actions/checkout`,
`actions/setup-python`, the `docker/*` actions, plain `run:` steps, and basic
contexts (`github.ref_name`, `github.actor`, `github.repository_owner`,
`secrets.*`). No GitHub-only contexts, no `concurrency` cancel groups, no app
tokens, no `type=gha` build cache.

## Concept mapping

| Concept | GitHub Actions (`.github/workflows/*.yml`) | Gitea/Forgejo Actions (`.gitea/workflows/*.yml` / `.forgejo/workflows/*.yml`) | GitLab CI (`.gitlab-ci.yml`) |
|---|---|---|---|
| Trigger: PR + push to main | `on: { pull_request, push: { branches: [main] } }` | Identical syntax | `workflow: rules:` on `$CI_PIPELINE_SOURCE == "merge_request_event"` or `$CI_COMMIT_BRANCH == "main"` |
| Trigger: tag `v*` | `on: { push: { tags: ['v*'] } }` | Identical syntax | `rules: - if: $CI_COMMIT_TAG =~ /^v/` |
| Checkout | `uses: actions/checkout@v4` | Identical (runner fetches the action from github.com by default; mirror or vendor it for air-gapped hosts) | Implicit — GitLab clones the repo before every job |
| Python setup | `uses: actions/setup-python@v5` with `python-version: '3.11'` | Identical (same action works; needs a runner image with node, e.g. `catthehacker/ubuntu:act-latest`) | `image: python:3.11` on the job |
| Run pytest | `run:` step: `pip install -e pipeline/ && python -m pytest pipeline/tests/ -q` | Identical | `script:` block, same commands |
| Docker build/push | `docker/setup-buildx-action@v3` + `docker/login-action@v3` + `docker/build-push-action@v6` | Same actions work; runner must have Docker socket access (or use DinD). Drop `type=gha` cache (GitHub-only — already dropped in `release.yml`) | `image: docker:27` + `services: [docker:27-dind]`; `docker login` / `docker build` / `docker push` in `script:` |
| Registry auth secret | `${{ secrets.GITHUB_TOKEN }}` → ghcr.io (auto-provisioned) | `${{ secrets.GITHUB_TOKEN }}` exists with the same name in Gitea Actions and authenticates to the Gitea container registry; for ghcr.io or another external registry, add a custom secret | `$CI_REGISTRY_USER` / `$CI_REGISTRY_PASSWORD` (auto) for the GitLab registry; custom CI/CD variables for external registries |
| Basic contexts | `github.ref_name`, `github.actor`, `github.repository_owner` | Identical names (Gitea implements the `github.*` context for compatibility) | `$CI_COMMIT_REF_NAME`, `$GITLAB_USER_LOGIN`, `$CI_PROJECT_NAMESPACE` |
| Runner label | `runs-on: ubuntu-latest` (GitHub-hosted) | `runs-on:` must match a **self-registered runner's label** — there are no hosted runners; `ubuntu-latest` works only if you registered a runner with that label | `tags:` selecting a registered runner, or omit for shared runners |
| Jobs / stages | `jobs:` (parallel by default, `needs:` for ordering) | Identical | `stages:` + per-job `stage:`; `needs:` for DAG ordering |

## Host-specific notes

- **Gitea/Forgejo:** workflow files move from `.github/workflows/` to
  `.gitea/workflows/` (Forgejo also reads `.forgejo/workflows/`). The YAML
  dialect is a deliberate GitHub-Actions clone, so `ci.yml` and `release.yml`
  port with ~zero edits beyond the directory move and confirming the runner
  label. The main operational difference is runners: you register your own
  (`act_runner`), and actions are fetched from github.com unless mirrored.
- **GitLab:** a real rewrite (different schema), but a small one — each job
  becomes an `image` + `script` block; see the sketch below.

```yaml
# .gitlab-ci.yml sketch (equivalent of ci.yml + release.yml)
stages: [test, release]

pipeline-tests:
  stage: test
  image: python:3.11
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == "main"
  script:
    - pip install -e pipeline/
    - python -m pytest pipeline/tests/ -q
    - PYTHONPATH=pipeline python -m evals.run_evals --check

release-image:
  stage: release
  image: docker:27
  services: [docker:27-dind]
  rules:
    - if: $CI_COMMIT_TAG =~ /^v/
  script:
    - docker login -u "$CI_REGISTRY_USER" -p "$CI_REGISTRY_PASSWORD" "$CI_REGISTRY"
    - docker build -f pipeline/deploy/Dockerfile -t "$CI_REGISTRY_IMAGE:$CI_COMMIT_TAG" .
    - docker run --rm "$CI_REGISTRY_IMAGE:$CI_COMMIT_TAG" python -m pytest pipeline/tests/ -q
    - docker push "$CI_REGISTRY_IMAGE:$CI_COMMIT_TAG"
    - docker tag "$CI_REGISTRY_IMAGE:$CI_COMMIT_TAG" "$CI_REGISTRY_IMAGE:latest"
    - docker push "$CI_REGISTRY_IMAGE:latest"
```
