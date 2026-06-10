# ICU-MUJICA Phase1 Eval Suite

This suite is a small first-pass benchmark for comparing ICU-MUJICA model profiles on front-end digital IC generation tasks.

It is designed to test the full harnessed workflow:

```text
User Request
  -> Parser / UserTaskSpec
  -> Architect / SpecReg
  -> Coder / RTL
  -> Evaluate / static contract + compile
  -> optional supplemental smoke TB
  -> artifacts / trace / repair records
```

## Case mix

The first suite has 10 cases:

| Case | Type | Input style | Main stress |
|---|---|---|---|
| C01 | Priority encoder | detailed natural language | combinational defaults / no latches |
| C02 | Round-robin arbiter | detailed natural language | state update / priority rotation |
| C03 | Sync FIFO 4x8 | detailed natural language | pointers / count / boundary behavior |
| C04 | PWM generator | vague natural language | assumption handling |
| C05 | Skid buffer | vague natural language | valid-ready protocol semantics |
| C06 | Pulse synchronizer | vague natural language | CDC assumptions |
| C07 | Timer IRQ | detailed JSON | structured spec fidelity |
| C08 | UART TX lite | detailed JSON | FSM / shift register / serial protocol |
| C09 | 2R1W regfile | vague JSON | semi-structured ambiguity |
| C10 | Sequence detector | vague JSON | FSM / overlap / valid gating |

Supplemental Verilog smoke/behavior testbenches are currently provided for deterministic cases:

```text
C01, C02, C03, C07, C08, Cextra
```

`Cextra_multi_submodules_staged_mux_fifo` is intentionally stricter than a smoke test. In addition to the Verilog TB, its case file declares static artifact checks for:

- Parser/UserTaskSpec decomposition of the hierarchical prompt, rather than one giant echoed requirement;
- SpecReg exact top-port preservation, async-low clock/reset declaration, exactly three required RTL module nodes, required file names, and required graph paths from TOP/mux/edge-detector/FIFO to TOP outputs;
- Generated RTL module declarations, required submodule files, required top-level instantiations, and absence of common SystemVerilog-only tokens.

The vague cases are intentionally not over-constrained by TB yet, because different models may make different but defensible assumptions. They should be scored by SpecReg quality, assumption handling, and manual/secondary review.

## Environment profiles

The runner expects env profiles at repo root:

```text
.env.gpt
.env.ds
```

For each run it copies `.env.<profile>` to `.env`. Secrets are not printed; generated `env_summary.redacted.json` masks API keys/tokens.

By default, the runner also passes the selected profile as an explicit non-persisted `llm` runtime payload to `POST /v1/workflow/run`. The saved `request_payload.json` is redacted, so API keys are not written to eval results. Use `--no-explicit-llm` only when you specifically want to test container-env-only behavior.

Default profiles:

```bash
gpt ds
```

## Main run

From repo root:

```bash
conda activate ICU-MUJICA
python eval/phase1_suite/scripts/run_phase1_suite.py --profiles gpt ds
```

Default behavior:

- backs up existing `.env` if present;
- copies `.env.<profile>` to `.env` for each profile;
- sends the profile's LLM runtime config explicitly in the workflow payload, with saved request payload redacted;
- for every profile/case pair:
  - `docker compose down -v --remove-orphans`
  - `docker compose up -d`
  - waits for Parser `/health`
  - calls `POST /v1/workflow/run`
  - collects API response and artifact summaries
  - runs supplemental smoke TB when available;
- restores previous `.env` at the end unless `--keep-env` is set.

## Dry run

```bash
python eval/phase1_suite/scripts/run_phase1_suite.py --dry-run
```

## Useful options

Run only selected cases:

```bash
python eval/phase1_suite/scripts/run_phase1_suite.py --profiles gpt ds --select C02_rr_arbiter4_detailed_nl C08_uart_tx_lite_detailed_json
```

Rebuild images only when source/container dependencies changed:

```bash
python eval/phase1_suite/scripts/run_phase1_suite.py --profiles gpt ds --rebuild
```

Do not reset docker per run:

```bash
python eval/phase1_suite/scripts/run_phase1_suite.py --profiles gpt ds --no-docker-reset
```

Test container-env-only LLM propagation instead of explicit runtime payload:

```bash
python eval/phase1_suite/scripts/run_phase1_suite.py --profiles gpt ds --no-explicit-llm
```

Override max iterations for all cases:

```bash
python eval/phase1_suite/scripts/run_phase1_suite.py --profiles gpt ds --max-iterations 1
```

Clean `shared_workspace/` before each run, preserving `.gitignore`:

```bash
python eval/phase1_suite/scripts/run_phase1_suite.py --profiles gpt ds --clean-shared-workspace
```

This is off by default to avoid deleting useful debugging artifacts.

## Output

Each suite run creates:

```text
eval/phase1_suite/results/run_<timestamp>/
  run_plan.json
  summary.csv
  summary.json
  <profile>/
    env_summary.redacted.json
    <case_id>/
      request_payload.json
      api_response.json
      summary.json
      docker_logs/
      smoke_tb.stdout.log   # if TB exists
      smoke_tb.stderr.log   # if TB exists
```

Raw ICU-MUJICA artifacts remain in the normal project output tree:

```text
output/TASK_.../
shared_workspace/TASK_.../
```

## Suggested scoring

For each run, score manually or with future scripts:

```text
SpecReg correctness       0/1/2
RTL compile/syntax        0/1/2
Behavior correctness      0/1/2
Assumption handling       0/1/2
Trace/evolution usability 0/1/2
```

The runner records machine-readable fields such as:

- API status / workflow success / final stage
- Evaluate verdict
- compile error count
- port mismatch count
- SpecReg size
- port count
- functional requirement count
- clock/reset structure count
- Architect repair frame count
- LLM transcript counts: Parser / Architect / Coder / Evaluate
- `invalid_llm_not_used`, which marks runs where LLM was expected but no Architect/Coder LLM transcript was produced
- smoke TB pass/fail
- strict static artifact checks when declared by a case:
  - `user_spec_check_pass` for Parser/UserTaskSpec decomposition and keyword coverage
  - `spec_check_pass` for exact ports, clock/reset, required nodes, required graph paths, and text keyword coverage
  - `rtl_check_pass` for required RTL files/modules/instantiations and forbidden token checks
  - `strict_static_check_pass`, a combined gate across declared static checks

These fields are intended to compare one-shot generation quality, schema-following quality, and harness usefulness across model profiles.
