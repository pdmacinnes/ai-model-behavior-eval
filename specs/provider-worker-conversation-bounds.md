# Spec: Configurable Provider Conversation Bounds

## Requirements & Goals

- Prevent legitimate long investigations from being classified as infrastructure-censored solely because the provider worker reaches its default conversation-round bound.
- Keep provider execution bounded and parent-owned. Raising a bound must not remove the subprocess timeout, workspace evidence budget, request-size bound, response-size bound, or JSONL output bound.
- Make conversation round, message-count, and conversation-character limits explicit in the reviewed worker command.
- Allow the model-matrix generator to create a new uniquely labeled batch for a rerun without overwriting the prior smoke artifacts.

## Inputs, Outputs & Behavior

- The provider worker CLI accepts positive integer values for:
  - `--max-rounds`;
  - `--max-conversation-messages`;
  - `--max-conversation-chars`.
- The worker applies the conversation bounds both in its loop and inside the provider transport request builder.
- The trusted execution policy allowlists only these numeric bounds in addition to the existing approved worker arguments. Duplicate, missing, non-integer, or non-positive values remain rejected.
- The model-matrix generator uses bounded pilot headroom of 24 rounds, 48 conversation messages, and 192,000 conversation characters. The existing parent trial timeout and evidence budget remain unchanged.
- The generator accepts a safe `--batch-label` and includes it in generated batch identifiers. The default remains `v1`; reruns use a new label such as `bounds-v2`.
- Existing registrations and artifacts are never overwritten. No live provider call occurs during implementation or verification.

## Edge Cases & Error Handling

- Non-positive or malformed conversation bounds fail before provider execution.
- A worker that still exceeds the explicit bound fails closed as an infrastructure error; the change does not convert exhaustion into a behavioral result.
- The transport and worker loop must use the same configured bounds so a transport-level default cannot censor a run earlier than the worker-level bound.
- The execution policy rejects unapproved worker flags and duplicate bound flags.
- A batch label must be a safe identifier and must not permit path separators or shell syntax.
- An existing batch label or output file remains protected by the current no-overwrite behavior.

## Acceptance Criteria

- [ ] Worker CLI parses and applies all three configurable conversation bounds.
- [ ] OpenAI-compatible, Responses, and native Gemini transports enforce the configured conversation bounds.
- [ ] Trusted execution policy accepts only the approved positive numeric bound flags.
- [ ] Matrix registrations include the reviewed 24-round, 48-message, and 192,000-character limits.
- [ ] Matrix generation supports a new safe batch label for reruns.
- [ ] Tests cover bound propagation, policy validation, malformed/duplicate flags, and batch-label generation.
- [ ] Existing tests remain green.
- [ ] Offline verification makes no provider requests.
