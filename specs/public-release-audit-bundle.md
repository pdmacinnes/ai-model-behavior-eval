# Spec: Public Release Audit Bundle

## Requirements & Goals

Make the sanitized public release self-describing enough to audit a published behavioral result without copying local registration files, commands, workspace paths, credentials, or hidden variant identifiers.

The release builder must derive all new metadata from already-public batch manifests and the repository's fixed reproduction instructions. It must not read or require the original registration JSON.

## Inputs, Outputs & Behavior

For every copied batch, write `batches/<batch-id>/registration.json` containing only:

- a public registration schema and batch id;
- registration and case-set hashes when present;
- harness version;
- sorted family ids and observed repetition values;
- `planned_trial_count`;
- public condition metadata: condition id, provider, model id, adapter id, reasoning effort, and network-required flag.

The projection must omit command, case root, artifacts root, workspace parent, variant ids, prompts, credentials, and environment values. It is derived from the sanitized batch manifest, not from a local registration file.

Write a root `README.md` with static contents explaining the release contents, the omitted raw artifacts, and the two offline commands for rebuilding the sanitized release and behavioral report. It must contain no machine-specific paths or secrets.

Extend the root release manifest with counts for public registration projections and the observation/report entrypoints. Existing case and run outputs remain unchanged.

## Edge Cases & Error Handling

- A batch manifest without `batch_id` uses its directory name, matching existing release behavior.
- A malformed or unsafe batch manifest still fails closed before any release files are written for that batch.
- Missing optional registration fields become null or empty lists; unknown fields are never copied.
- The generated README is deterministic and does not mention the source machine or local registration path.
- Existing excluded artifacts remain excluded.

## Acceptance Criteria

- [ ] Every copied batch has a public registration projection with no forbidden fields or local paths.
- [ ] The release root has deterministic reproduction instructions and report-building instructions.
- [ ] The root manifest records registration projection and entrypoint metadata.
- [ ] Tests prove commands, paths, variant ids, prompts, and credentials from source-like data cannot appear in the public bundle.
- [ ] Existing sanitizer, report, and full-suite tests pass.
- [ ] The completed change is committed separately from user-local registration files.
