"""Cost Tracker — aggregation and reporting for project costs.

Tier 6: Aggregates usage data from costs/usage.jsonl by task, tier, provider,
role, and model. Produces human-readable cost reports.

All functions are pure — they load from JSONL and compute aggregates.
"""

from __future__ import annotations

from orchestration.lineage import load_usage


# ---------------------------------------------------------------------------
# Aggregation functions
# ---------------------------------------------------------------------------

def aggregate_costs_by_task(project_id: str, projects_dir: str) -> dict[str, float]:
    """Sum estimated_cost by task_id."""
    entries = load_usage(project_id, projects_dir)
    result: dict[str, float] = {}
    for e in entries:
        task_id = e.get("task_id", "unknown")
        result[task_id] = result.get(task_id, 0.0) + e.get("estimated_cost", 0.0)
    return result


def aggregate_costs_by_tier(project_id: str, projects_dir: str) -> dict[int, float]:
    """Sum estimated_cost by tier."""
    entries = load_usage(project_id, projects_dir)
    result: dict[int, float] = {}
    for e in entries:
        tier = e.get("tier", 0)
        result[tier] = result.get(tier, 0.0) + e.get("estimated_cost", 0.0)
    return result


def aggregate_costs_by_provider(project_id: str, projects_dir: str) -> dict[str, float]:
    """Sum estimated_cost by provider."""
    entries = load_usage(project_id, projects_dir)
    result: dict[str, float] = {}
    for e in entries:
        provider = e.get("provider", "unknown")
        result[provider] = result.get(provider, 0.0) + e.get("estimated_cost", 0.0)
    return result


def aggregate_costs_by_role(project_id: str, projects_dir: str) -> dict[str, float]:
    """Sum estimated_cost by role (architect/builder/reviewer)."""
    entries = load_usage(project_id, projects_dir)
    result: dict[str, float] = {}
    for e in entries:
        role = e.get("role", "unknown")
        result[role] = result.get(role, 0.0) + e.get("estimated_cost", 0.0)
    return result


def aggregate_costs_by_model(project_id: str, projects_dir: str) -> dict[str, dict]:
    """Aggregate by model → {input_tokens, output_tokens, cost, call_count}."""
    entries = load_usage(project_id, projects_dir)
    result: dict[str, dict] = {}
    for e in entries:
        model = e.get("model", "unknown")
        if model not in result:
            result[model] = {
                "input_tokens": 0,
                "output_tokens": 0,
                "cost": 0.0,
                "call_count": 0,
            }
        result[model]["input_tokens"] += e.get("input_tokens", 0)
        result[model]["output_tokens"] += e.get("output_tokens", 0)
        result[model]["cost"] += e.get("estimated_cost", 0.0)
        result[model]["call_count"] += 1
    return result


def total_project_cost(project_id: str, projects_dir: str) -> float:
    """Sum all estimated_cost entries."""
    entries = load_usage(project_id, projects_dir)
    return sum(e.get("estimated_cost", 0.0) for e in entries)


# ---------------------------------------------------------------------------
# Human-readable report
# ---------------------------------------------------------------------------

def format_cost_report(project_id: str, projects_dir: str) -> str:
    """Produce a human-readable multi-section cost report."""
    entries = load_usage(project_id, projects_dir)
    if not entries:
        return f"Cost Report for {project_id}\n{'=' * 40}\nNo usage data recorded.\n"

    total = sum(e.get("estimated_cost", 0.0) for e in entries)
    total_input = sum(e.get("input_tokens", 0) for e in entries)
    total_output = sum(e.get("output_tokens", 0) for e in entries)

    lines = [
        f"Cost Report for {project_id}",
        "=" * 40,
        "",
        f"Total Cost:     ${total:.4f}",
        f"Total Tokens:   {total_input} in / {total_output} out",
        f"Total Calls:    {len(entries)}",
        "",
    ]

    # By tier
    by_tier = aggregate_costs_by_tier(project_id, projects_dir)
    if by_tier:
        lines.append("By Tier:")
        for tier in sorted(by_tier.keys()):
            lines.append(f"  Tier {tier}: ${by_tier[tier]:.4f}")
        lines.append("")

    # By provider
    by_provider = aggregate_costs_by_provider(project_id, projects_dir)
    if by_provider:
        lines.append("By Provider:")
        for provider, cost in sorted(by_provider.items()):
            lines.append(f"  {provider}: ${cost:.4f}")
        lines.append("")

    # By role
    by_role = aggregate_costs_by_role(project_id, projects_dir)
    if by_role:
        lines.append("By Role:")
        for role, cost in sorted(by_role.items()):
            lines.append(f"  {role}: ${cost:.4f}")
        lines.append("")

    # Top tasks by cost
    by_task = aggregate_costs_by_task(project_id, projects_dir)
    if by_task:
        lines.append("Top Tasks:")
        sorted_tasks = sorted(by_task.items(), key=lambda x: x[1], reverse=True)
        for task_id, cost in sorted_tasks[:10]:
            lines.append(f"  {task_id}: ${cost:.4f}")
        lines.append("")

    # By model
    by_model = aggregate_costs_by_model(project_id, projects_dir)
    if by_model:
        lines.append("By Model:")
        for model, stats in sorted(by_model.items()):
            lines.append(
                f"  {model}: ${stats['cost']:.4f} "
                f"({stats['call_count']} calls, "
                f"{stats['input_tokens']} in / {stats['output_tokens']} out)"
            )
        lines.append("")

    return "\n".join(lines)
