# Action Contract Spec

The boundary layer between AI-composed decisions and deterministic engine execution.

**Core rule:** AI may compose actions. Only the engine may execute them.
No contract → no effect on simulation state.

---

## Definitions

| Term | Meaning |
|------|---------|
| **Action Primitive** | A single legal verb from the Action Primitive Catalog |
| **Action Contract** | A validated bundle of one or more primitives with parameters |
| **Action Bundle** | A user-visible option composed of contracts that execute together |

---

## Layer Responsibilities

### Engine (L0)
**Owns:** primitive registry, parameter validation, constraint enforcement, execution, state transitions.
**Rejects:** unknown verbs, invalid parameters, constraint violations, unauthorized mutations.

### AI Moderator
**May:** read state, read constraints, select valid primitives, compose bundles, translate to human-readable options, estimate outcomes.
**Must not:** invent primitives, bypass validation, force execution, alter rules, write state directly.

### UX Layer
**Displays:** option descriptions, consequence previews, tradeoffs, uncertainty flags.
**Collects:** user selection.
**Never:** executes directly.

---

## Primitive Requirements

Every primitive in the catalog must define:

```
verb:               string              (from catalog)
required_params:    {name: type}        (must be provided)
optional_params:    {name: type}        (defaults apply)
valid_targets:      entity_type[]       (what it can act on)
constraint_checks:  constraint_id[]     (validated before execution)
side_effects:       system_id[]         (what else changes)
action_cost:        int                 (action slots consumed)
time_cost:          duration | null     (ticks until effect)
```

---

## Contract Validation Pipeline

Every contract passes through this pipeline before execution. All checks must pass.

| Step | Check | On Failure |
|------|-------|-----------|
| 1 | Verb exists in catalog | Reject: unknown verb |
| 2 | Target exists in state | Reject: invalid target |
| 3 | Target type matches verb's valid_targets | Reject: type mismatch |
| 4 | Required parameters provided and typed correctly | Reject: parameter error |
| 5 | Constraints satisfied | Reject: constraint violation (report which) |
| 6 | Resources available | Reject: insufficient resources (report shortfall) |
| 7 | No rule conflicts | Reject: rule conflict (report which rule) |

If any step fails: contract is rejected, AI moderator is notified with the failure reason, option is removed or revised.

**No partial validation.** A contract either passes all checks or is fully rejected.

---

## AI Composition Rules

AI builds options from: `VALID_PRIMITIVES ∩ CURRENTLY_ALLOWED_ACTIONS`

**Composition sequence:**
1. Detect pressure (from constraint registry)
2. Identify affected entities
3. Query valid primitives for those entity types
4. Filter by current constraints
5. Compose bundles
6. Estimate outcomes (range-based, not precise)
7. Attach metadata (confidence, uncertainty, tradeoffs)
8. Present to UX layer

**Every AI-composed option must include:**
- Confidence score (how likely is the projected outcome)
- Constraint notes (what limits apply)
- Uncertainty notes (what data is incomplete or delayed)
- Tradeoff summary (what gets worse if this improves)

---

## Bundle Execution Types

### Atomic Bundle
All primitives succeed or none execute.

- Used for: safety-critical actions, tightly coupled operations
- On failure: full rollback, no state change, failure reason logged
- Declared as: `bundle_type: atomic`

### Sequential Bundle
Primitives execute in declared order. Later primitives may fail.

- Used for: operational workflows, multi-step processes
- On partial failure: **executed primitives stand**, failed primitive and all subsequent are skipped
- State reflects the partial execution
- Failure reason and execution boundary are logged
- AI moderator is notified of partial completion for re-assessment
- Declared as: `bundle_type: sequential`

### Rollback Policy (Sequential Only)
Each sequential bundle must declare one of:

| Policy | Behavior |
|--------|----------|
| `commit_partial` | Keep completed steps, skip remainder. Default. |
| `rollback_all` | Undo all completed steps if any step fails. Functions like atomic. |
| `rollback_to_checkpoint` | Undo to last declared checkpoint primitive in the sequence. |

Checkpoints are marked in the primitive sequence: `checkpoint: true` on specific entries.

---

## User Selection Flow

```
1. AI moderator surfaces option bundles
2. User selects an option
3. Bundle → Contract Validator (full pipeline)
4. Validator approves or rejects
5. If approved → Engine executes primitives in declared order
6. State updates propagate
7. Events logged to ledger
8. Metrics updated
9. If rejected → UX shows reason + AI recomputes alternatives
```

---

## Determinism Guarantee

Given the same state and the same contract bundle, the engine must produce the same outcome.

AI narration may vary between runs. Execution results may not.

---

## Constraint Supremacy

Constraints override both AI and user intent.

If a contract violates a constraint, it fails. There is no override mechanism except changing the constraint itself (which is a policy action, also subject to validation).

No partial execution of atomic bundles. No constraint relaxation by the AI layer.

---

## Explainability

Every executed contract produces:

```
execution_log:
  contract_id:      string
  tick:             int
  primitives_executed: [{verb, params, result}]
  state_deltas:     [{entity_id, field, old_value, new_value}]
  resources_consumed: [{resource, amount}]
  events_generated: event_id[]
  constraints_checked: [{constraint_id, status}]
```

This supports replay, audit, AI narration, and user trust.

---

## UX Display Requirements

Every option shown to the user must include:

| Field | Purpose |
|-------|---------|
| Verbs involved | Plain-language action description |
| Targets affected | What entities change |
| Main benefit | Primary expected improvement |
| Main tradeoff | What gets worse |
| Resource cost | What is consumed |
| Time impact | How long until effect |
| Uncertainty | What is unknown or estimated |

No hidden actions. No invisible tradeoffs. No suppressed failures.

---

## Failure UX

When a selected contract fails validation, the user sees:

1. **What failed** — plain-language description of the rejected action
2. **Why** — the specific constraint or rule that blocked it
3. **What would need to change** — the condition that would make it valid
4. **Alternatives** — AI-recomputed options that are currently valid

This is where user trust is built. A clear rejection with a good explanation is better than a mysterious limitation.

---

## AI Guardrails

The AI moderator must not:
- Create actions not composed from catalog primitives
- Merge contracts in ways that hide individual primitive effects
- Suppress constraint failure information from the user
- Auto-execute without user approval (unless L4 delegation is active and scoped)
- Present options where the tradeoff is obscured

---

## Testability Rule

You must be able to list every action primitive in a single document (the catalog).
If you cannot, the AI has too much power and the system is not testable.

Finite verbs = testable, auditable, replayable system.

---

## Success Criteria

The boundary is correctly implemented if:
- AI-surfaced options feel organic (derived from state, not scripted)
- Outcomes remain deterministic (same input → same result)
- No scripted decision trees exist anywhere
- Engine rules are never bypassed
- Every user decision maps to validated primitives
- Failed actions produce clear, useful explanations
