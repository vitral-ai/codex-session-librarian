"""Deterministic scenario model. Estimates, not remote performance measurements."""

import itertools
import math
import random

SEED = 20261109


def scenario(n, days, size, fraction, hours, growth):
    runs_per_day = 24 // hours
    changed = math.ceil(n * fraction)
    runs = days * runs_per_day
    objects = n + (runs - 1) * changed
    # Equal-probability changes and uniform mean sizes; whole sessions, not deltas.
    uploads = 0
    peak_run = 0
    for day in range(days):
        current_size = math.ceil(size * (1 + growth) ** day)
        count = (n if day == 0 else changed) + (runs_per_day - 1) * changed
        uploads += count * current_size
        peak_run = max(peak_run, (n if day == 0 else changed) * current_size)
    final_size = math.ceil(size * (1 + growth) ** (days - 1))
    # New objects + catalogs fully downloaded at publication; small descriptors
    # estimated 512B; catalog entry estimated 2048B. No compression assumed.
    catalog = n * 2048
    releases = objects + runs
    assets = 2 * releases
    leases_per_run = 3  # acquire + durable batch intentions + commit; sensitivity below
    control_commits = runs * leases_per_run
    # release+2 assets: 3 writes; intent+verification metadata: assumed 5 calls.
    # control: blob/tree/commit/ref and two reads per acquisition+commit (10/run).
    writes = releases * 3 + control_commits * 4
    api_calls = releases * 8 + runs * (n + 10)
    metadata_pages = math.ceil(releases / 100)
    # Distinct scopes: current heads versus all retained historical versions.
    # Both are size upper estimates at the final-day mean, not a promise that a
    # real verifier can afford or should perform all historical reads.
    reverify_heads = (days // 30) * n * final_size
    reverify_history = sum((n + (day * runs_per_day - 1) * changed) *
                          math.ceil(size * (1 + growth) ** (day - 1))
                          for day in range(30, days + 1, 30))
    max_size = final_size
    return {"sessions": n, "days": days, "mean_initial_bytes": size,
        "changed_fraction": fraction, "hours": hours, "growth_daily": growth,
        "runs": runs, "objects": objects, "releases": releases, "assets": assets,
        "upload_bytes": uploads + runs * catalog + releases * 512,
        "publication_full_download_bytes": uploads + runs * catalog,
        "full_every_run_download_bytes": sum(n * math.ceil(size * (1+growth)**d) * runs_per_day for d in range(days)),
        "light_reuse_queries": runs * n - objects,
        "full_30d_current_heads_upper_bytes": reverify_heads,
        "full_30d_retained_history_upper_bytes": reverify_history,
        "pending_historical_verification_objects_upper": objects,
        "pre_restore_bytes": n * final_size + catalog,
        "restore_calls": n * 2 + metadata_pages,
        "catalog_bytes": catalog, "max_object_bytes": max_size,
        "control_commits_minimum": control_commits,
        "control_commits_one_hour_runs_60s_renewal": runs * 62,
        "control_metadata_estimated_bytes": control_commits * 2048,
        "api_calls": api_calls, "api_calls_per_run_mean": api_calls / runs,
        "api_calls_per_hour_mean": api_calls / (days * 24),
        "content_writes": writes, "content_writes_per_run_mean": writes / runs,
        "bootstrap_content_writes_lower_bound": (n + 1) * 3 + 12,
        "incremental_content_writes_lower_bound": (changed + 1) * 3 + 12,
        "bootstrap_exceeds_500_writes_hour": (n + 1) * 3 + 12 > 500,
        "control_commits_per_object_intent_sensitivity": control_commits + objects,
        "content_writes_per_object_intents_sensitivity": writes + objects * 4,
        "content_writes_60s_renewal_sensitivity": writes + runs * 59 * 4,
        "bootstrap_500_writes_minimum_hours": math.ceil(((n+1)*3+12) / 500),
        "bootstrap_80_writes_minimum_minutes": math.ceil(((n+1)*3+12) / 80),
        "control_metadata_per_object_intent_bytes": (control_commits + objects) * 2048,
        "list_metadata_memory_estimated_bytes": releases * 2048,
        "list_time_at_2_requests_second": metadata_pages / 2,
        "list_pages_without_control": metadata_pages,
        "normal_discovery_calls_with_valid_control_estimate": 6,
        "peak_run_bytes": peak_run,
        "projected_exceeds_1250_api_hourly_mean": api_calls / (days*24) > 1250,
        "projected_exceeds_500_content_hourly_mean": writes / (days*24) > 500,
        "exceeds_256MiB_object": max_size > 256 * 1024**2,
        "exceeds_16MiB_catalog": catalog > 16 * 1024**2,
        "exceeds_2GiB_run": peak_run > 2 * 1024**3,
        "minimum_upload_seconds_at_10MiBps": peak_run / (10 * 1024**2),
        "naive_gc_listing_pages": metadata_pages,
        "grouping_100_objects_release_pages_estimate": math.ceil((math.ceil(objects / 100) + runs) / 100)}


def matrix():
    axes = ([100, 1000, 10000], [30, 90, 365], [64*1024, 1024**2, 8*1024**2],
            [.01, .1, .5], [24, 6, 1], [0, .01, .05])
    combinations = list(itertools.product(*axes))
    random.Random(SEED).shuffle(combinations)
    return [scenario(*args) for args in combinations]


def container_comparison(n=1000, size=1024**2, fraction=.1, capacity=64*1024**2):
    """Offline alternative only: one encrypted bounded container per packed group."""
    changed = math.ceil(n * fraction)
    headroom = 1024**2
    def layout(logical):
        if size > capacity - headroom:
            return {"supported_without_member_splitting": False}
        members = (capacity - headroom) // size
        containers = math.ceil(logical / members)
        releases = containers + 1
        base_writes = releases * 3 + 12
        return {"logical_versions": logical, "physical_containers": containers,
            "releases_including_checkpoint": releases, "assets": releases * 2,
            "writes_batched_intent": base_writes,
            "writes_per_container_intent": base_writes + containers * 4,
            "minimum_minutes_80_writes_with_container_intents": math.ceil((base_writes + containers*4)/80),
            "minimum_hours_500_writes_with_container_intents": math.ceil((base_writes + containers*4)/500),
            "upload_bytes_before_compression": logical * size,
            "single_member_download_amplification_upper": min(members, logical),
            "members_per_container_max": members,
            "control_commits_minimum": 3,
            "control_commits_per_container_intent": 3 + containers}
    return {"scope": "offline alternative, NOT adopted contract or implemented format",
        "capacity_bytes": capacity, "packing_headroom_estimate_bytes": headroom,
        "final_ciphertext_check_required": True, "bootstrap": layout(n), "incremental": layout(changed),
        "costs": ["individual restore may download/decrypt up to container size",
                  "retention of one member retains its whole container unless repacked into a NEW container",
                  "changed sessions appended to new containers; unchanged versions keep old member references"],
        "required_bindings": ["logical version_key", "logical UUID", "container UUID/checksum",
                              "member path/length/hash inside encrypted catalog", "per-session restore receipt"]}
