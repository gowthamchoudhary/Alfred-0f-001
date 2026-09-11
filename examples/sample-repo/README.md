# Sample repo — Alfred contract reference

This directory is **not** wired into Alfred's code. It exists as a minimal,
runnable example of the [repo contract](../../README.md#the-repo-contract) so
you can validate an install quickly:

```bash
python -m alfred.cli investigate ./examples/sample-repo 2.1.0
```

Alfred will bump `openai` to 2.1.0 in a candidate copy of this repo, build and
run both, execute `tests/` inside each container, load `/chat` per
`alfred.yaml`, compare, decide, and (if `GITHUB_TOKEN` is set) post the issue.

Point Alfred at **your** repo instead — anything with `Dockerfile`,
pinned `requirements.txt`, `tests/`, and `alfred.yaml` works.
