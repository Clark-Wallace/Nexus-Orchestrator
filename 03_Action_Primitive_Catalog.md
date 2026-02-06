# Action Primitive Catalog

The complete set of legal simulation verbs.
AI may compose these into options. The engine executes them. Users see translated descriptions, never raw verbs.

**If a verb is not in this catalog, it does not exist.**

---

## Design Rules

- Verb set is **finite and closed** — no verb invention at runtime
- Every parameter has a type and validation rule
- No narrative verbs (e.g., `describe_situation`)
- No outcome verbs (e.g., `succeed`, `fail`)
- Only operational verbs that mutate state through the engine
- All verbs are domain-agnostic — domain meaning comes from the entities they target

---

## Parameter Type Reference

| Type | Definition |
|------|-----------|
| `entity_id` | Valid ID in the current state tree |
| `resource_enum` | Defined resource type for this sim |
| `float+` | Positive float, validated against available amount |
| `percent` | Float [0.0, 1.0] |
| `duration` | Positive integer (ticks) |
| `mode_enum` | Valid operating mode for target entity |
| `priority_level` | Integer or enum per policy definition |
| `path_id` | Valid route/path in topology |
| `policy_id` | Registered policy identifier |
| `agent_id` | Valid AI agent or team identifier |
| `task_id` | Valid task in schedule |

---

## A — Resource Control

| Verb | Signature | Effect |
|------|-----------|--------|
| `allocate_resource` | `(target: entity_id, resource: resource_enum, amount: float+)` | Move resource toward target. Validated against pool availability. |
| `reallocate_resource` | `(source: entity_id, target: entity_id, resource: resource_enum, amount: float+)` | Shift assigned resource between entities. Source must hold amount. |
| `reserve_resource` | `(pool: entity_id, resource: resource_enum, amount: float+)` | Hold resource from general availability. Creates reservation lock. |
| `release_resource` | `(pool: entity_id, resource: resource_enum, amount: float+)` | Return reserved resource to available pool. |
| `increase_production` | `(source: entity_id, rate_delta: float+)` | Raise output. Validated against source capacity. |
| `decrease_production` | `(source: entity_id, rate_delta: float+)` | Lower output rate. |
| `consume_reserve` | `(pool: entity_id, resource: resource_enum, amount: float+)` | Draw from emergency reserves. Triggers reserve depletion tracking. |

---

## B — Personnel and Crew

| Verb | Signature | Effect |
|------|-----------|--------|
| `dispatch_team` | `(team: entity_id, destination: entity_id)` | Send crew. Validated: team available, route accessible. |
| `recall_team` | `(team: entity_id)` | Pull team back. Creates travel-time delay. |
| `reassign_team` | `(team: entity_id, new_role: mode_enum)` | Change team function. May require transition time. |
| `augment_staff` | `(target: entity_id, amount: float+)` | Temporarily increase staffing from available pool. |
| `reduce_staff` | `(target: entity_id, amount: float+)` | Reduce staffing. Released to pool. |
| `extend_shift` | `(team: entity_id, duration: duration)` | Increase duty window. Validated against fatigue/policy rules. |
| `standby_team` | `(team: entity_id)` | Hold ready, not deployed. Occupies team but no active output. |

---

## C — Routing and Flow

| Verb | Signature | Effect |
|------|-----------|--------|
| `reroute_flow` | `(flow: entity_id, new_path: path_id)` | Change flow route. Validated against path capacity. |
| `throttle_flow` | `(flow: entity_id, percent: percent)` | Reduce throughput to specified fraction. |
| `increase_flow` | `(flow: entity_id, percent: percent)` | Increase throughput. Capped at flow capacity. |
| `isolate_node` | `(node: entity_id)` | Disconnect node from network. Triggers downstream cascade check. |
| `reconnect_node` | `(node: entity_id)` | Restore node. May require safety checks. |
| `prioritize_route` | `(route: path_id, priority: priority_level)` | Raise route priority in flow resolution. |
| `deprioritize_route` | `(route: path_id, priority: priority_level)` | Lower route priority. |

---

## D — Load and Demand

| Verb | Signature | Effect |
|------|-----------|--------|
| `shed_load` | `(group: entity_id, amount: float+)` | Remove noncritical demand. Validated against shedding rules. |
| `shift_load` | `(source_group: entity_id, target_group: entity_id)` | Move demand to different service point. |
| `cap_demand` | `(group: entity_id, max_level: float+)` | Impose upper limit on consumption. |
| `defer_demand` | `(group: entity_id, duration: duration)` | Delay demand fulfillment. Creates queued backlog. |
| `stagger_demand` | `(group: entity_id, window: duration)` | Spread demand over time window. |

---

## E — Asset and Infrastructure

| Verb | Signature | Effect |
|------|-----------|--------|
| `activate_backup` | `(asset: entity_id)` | Bring standby system online. Startup delay applies. |
| `deactivate_asset` | `(asset: entity_id)` | Take system offline. Triggers dependency cascade check. |
| `switch_mode` | `(asset: entity_id, mode: mode_enum)` | Change operating mode. Validated against allowed transitions. |
| `increase_redundancy` | `(asset: entity_id)` | Add backup pairing from available pool. |
| `reduce_redundancy` | `(asset: entity_id)` | Remove backup for efficiency. Increases risk exposure. |
| `patch_asset` | `(asset: entity_id)` | Quick repair. Partial condition improvement, not full restoration. |
| `stabilize_asset` | `(asset: entity_id)` | Temporary condition hold. Prevents further degradation for duration. |

---

## F — Maintenance and Repair

| Verb | Signature | Effect |
|------|-----------|--------|
| `schedule_repair` | `(asset: entity_id, priority: priority_level)` | Add to repair queue at priority. |
| `accelerate_repair` | `(asset: entity_id)` | Spend extra resources to speed repair. Cost validated. |
| `delay_repair` | `(asset: entity_id)` | Push repair later in queue. |
| `cancel_repair` | `(asset: entity_id)` | Remove from repair queue. |
| `inspect_asset` | `(asset: entity_id)` | Trigger condition evaluation. Updates observed state. |
| `swap_asset` | `(asset_a: entity_id, asset_b: entity_id)` | Exchange roles/positions. Both must be compatible type. |

---

## G — Priority and Policy

| Verb | Signature | Effect |
|------|-----------|--------|
| `prioritize_entity` | `(entity: entity_id, level: priority_level)` | Raise in allocation/attention order. |
| `deprioritize_entity` | `(entity: entity_id, level: priority_level)` | Lower in allocation order. |
| `protect_entity` | `(entity: entity_id)` | Mark as protected. Receives priority in shedding decisions. |
| `sacrifice_entity` | `(entity: entity_id)` | Allow controlled degradation. Removes protection. |
| `lock_policy` | `(policy: policy_id)` | Prevent policy changes. |
| `unlock_policy` | `(policy: policy_id)` | Allow policy changes. |

---

## H — Capacity Management

| Verb | Signature | Effect |
|------|-----------|--------|
| `expand_capacity` | `(entity: entity_id, amount: float+)` | Temporary boost. Validated against expansion limits. |
| `contract_capacity` | `(entity: entity_id, amount: float+)` | Reduce capacity. May trigger load shedding. |
| `convert_capacity` | `(entity: entity_id, from_type: resource_enum, to_type: resource_enum)` | Repurpose capability. Conversion rules apply. |
| `buffer_capacity` | `(entity: entity_id, amount: float+)` | Add safety margin. Reduces usable capacity. |
| `release_capacity` | `(entity: entity_id)` | Remove buffer. Restores full usable capacity. |

---

## I — Communication and Information

| Verb | Signature | Effect |
|------|-----------|--------|
| `issue_advisory` | `(group: entity_id)` | Send warning. Updates information state for affected entities. |
| `issue_restriction` | `(group: entity_id)` | Impose operational limitation. |
| `request_status` | `(entity: entity_id)` | Force telemetry update. Reduces information delay for target. |
| `increase_monitoring` | `(entity: entity_id)` | Raise observation frequency. Costs monitoring resources. |
| `reduce_monitoring` | `(entity: entity_id)` | Lower observation frequency. Saves resources, increases delay. |

---

## J — Logistics

| Verb | Signature | Effect |
|------|-----------|--------|
| `dispatch_supply` | `(resource: resource_enum, destination: entity_id)` | Send material. Creates shipment with travel time. |
| `reroute_supply` | `(shipment: entity_id, new_destination: entity_id)` | Change in-transit destination. |
| `hold_shipment` | `(shipment: entity_id)` | Pause movement. |
| `expedite_shipment` | `(shipment: entity_id)` | Increase speed. Higher cost. |
| `split_shipment` | `(shipment: entity_id, split_amount: float+)` | Divide load into two shipments. |
| `combine_shipments` | `(shipments: entity_id[])` | Merge loads. Must share destination. |

---

## K — Time and Schedule

| Verb | Signature | Effect |
|------|-----------|--------|
| `advance_task` | `(task: task_id)` | Move earlier in schedule. |
| `delay_task` | `(task: task_id)` | Move later. |
| `pause_task` | `(task: task_id)` | Suspend execution. |
| `resume_task` | `(task: task_id)` | Restart suspended task. |
| `compress_schedule` | `(entity: entity_id)` | Shorten timeline. May increase resource burn. |
| `stretch_schedule` | `(entity: entity_id)` | Lengthen timeline. Reduces resource pressure. |

---

## L — Risk and Safety

| Verb | Signature | Effect |
|------|-----------|--------|
| `increase_safety_margin` | `(entity: entity_id)` | Raise buffers. Reduces operational capacity. |
| `reduce_safety_margin` | `(entity: entity_id)` | Accept more risk. Increases operational capacity. |
| `enter_safe_mode` | `(entity: entity_id)` | Switch to low-risk operation. Reduced output. |
| `exit_safe_mode` | `(entity: entity_id)` | Return to normal operation. |
| `quarantine_node` | `(node: entity_id)` | Isolate for safety. Similar to `isolate_node` but with safety-hold flag. |

---

## M — Delegation (AI L4 Compatible)

| Verb | Signature | Effect |
|------|-----------|--------|
| `delegate_task` | `(task: task_id, agent: agent_id)` | Assign to AI agent. Agent operates within policy bounds. |
| `revoke_delegation` | `(task: task_id)` | Return to user control. |
| `set_autopolicy` | `(policy: policy_id)` | Allow AI auto-execution within policy scope. |
| `limit_autopolicy` | `(policy: policy_id)` | Constrain AI authority for this policy. |

---

## Composition Rules

AI composes user-facing options by combining: `target entity × valid verbs × current constraints`

**AI must:**
- Only select verbs from this catalog
- Validate targets exist in current state
- Check constraints before presenting options
- Attach confidence and uncertainty notes

**AI must not:**
- Invent verbs not listed here
- Compose verbs that skip engine validation
- Present options with invalid targets
- Hide constraint violations from the user

---

## Completeness Test

If every simulation-changing action can be expressed using verbs from this catalog, the system remains deterministic, testable, replayable, and AI-safe.

If an action requires a verb not in this catalog, the catalog must be formally extended — not worked around.
