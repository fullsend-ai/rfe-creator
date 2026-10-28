# RFE Creator Fullsend Agent

**Note**: the Fullsend agent for `rfe-creator` is under development and in an early
stage. It supports local execution and heavily customized workflows only; it is not
yet ready for the default Fullsend workflows on GitHub or GitLab. See the
[fullsend documentation](https://fullsend.sh) for running agents locally, and the
[rfe-creator agent README](./rfe-creator/README.md) for this agent's setup.

This folder contains the agent implemented for [Fullsend](https://fullsend.sh) that
makes use of the RFE Creator skills.

To use this agent from another repository, add it to your configuration file with:

```bash
fullsend agent add --fullsend-dir .fullsend https://github.com/fullsend-ai/rfe-creator/blob/main/.fullsend/rfe-creator/rfe-creator.yaml
```

This adds the following to your `.fullsend/config.yaml`:

```yaml
agents:
- source: https://raw.githubusercontent.com/fullsend-ai/rfe-creator/<SHA>/.fullsend/rfe-creator/rfe-creator.yaml#sha256=<SHA256>
  ref: main
allowed_remote_resources:
  - https://raw.githubusercontent.com/fullsend-ai/fullsend/
  - https://raw.githubusercontent.com/fullsend-ai/agents/
  - https://raw.githubusercontent.com/fullsend-ai/rfe-creator/
```

From a checkout of this repository, run it directly with
`fullsend run rfe-creator --fullsend-dir .fullsend --target-repo . --env-file .env`;
the
[rfe-creator agent README](./rfe-creator/README.md) lists the prerequisites and
environment variables.

This repository's own `.fullsend/config.yaml` is not edited here: the fleet sync renders
it from the `fullsend-ai/rfe-creator` entry of the manifest
[`fullsend-ai/.fullsend/repos.yaml`](https://github.com/fullsend-ai/.fullsend/blob/main/repos.yaml)
on every fullsend release, weekly, or by hand, overwriting the file. An agent of this
package (`rfe-creator`, the eval variant `rfe-creator-eval`) is registered by a pull
request on that manifest, never by a line added to `config.yaml` (such a line was dropped
by the sync on 2026-10-28, fullsend-ai/.fullsend#203 restored the eval agent).
`tests/test_fullsend_eval_harness.py` fails when the rendered file lacks the eval agent.
