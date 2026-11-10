"""F0 synthetic/local prototypes; no real histories, remote calls or model turns."""

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import uuid

from experiments.backup_f0 import backend, contracts as c, scale
from experiments.backup_f0.control import Conflict, GitControl


def example(rule):
    if "enum" in rule:
        return rule["enum"][0]
    if rule.get("type") == "object":
        return {key: example(child) for key, child in rule["properties"].items()}
    if rule.get("type") == "array":
        return []
    if rule.get("type") == "boolean":
        return False
    if rule.get("type") == "integer":
        return rule.get("minimum", 0)
    if rule.get("format") == "uuid":
        return "11111111-1111-4111-8111-111111111111"
    if rule.get("format") == "utc":
        return "2026-11-09T00:00:00Z"
    if rule.get("pattern", "").startswith("^members/"):
        return "members/11111111-1111-4111-8111-111111111111.jsonl"
    if "pattern" in rule:
        return "a" * 64
    return "synthetic"


def examples():
    result = {name: example(rule) for name, rule in c.SCHEMAS.items()}
    entry = example(c.ENTRY)
    entry["version_key"] = c.digest(entry["identity"])
    result["catalog"].update(entries=[entry], failures=[], exclusions=[],
                             counts={"eligible": 1, "succeeded": 1, "failed": 0, "excluded": 0})
    result["config"]["fingerprint"].update(cipher="age-v1-x25519",
        recipients=["age1" + "a" * 58, "age1" + "c" * 58])
    result["config"]["key_reference"] = "keyring:synthetic-fixture-reference"
    for name in ("container", "layout"):
        result[name]["members"] = [example(c.MEMBER)]
    return result


class BackupContractsTests(unittest.TestCase):
    def test_valid_vectors_and_schema_version_fail_closed(self):
        for name, vector in examples().items():
            with self.subTest(name=name):
                c.validate(name, vector)
                bad = {**vector, "schema_version": 2}
                with self.assertRaises(ValueError):
                    c.validate(name, bad)
                with self.assertRaises(ValueError):
                    c.validate(name, {**vector, "token": "not-a-credential"})

    def test_canonical_deterministic_and_no_ambiguous_numeric_types(self):
        self.assertEqual(c.canonical({"z": 1, "a": "fixture"}), b'{"a":"fixture","z":1}')
        for value in (float("nan"), 1.0, {1: "wrong"}):
            with self.assertRaises(ValueError):
                c.canonical(value)
        config = examples()["config"]
        config["repo_id"] = True
        with self.assertRaises(ValueError):
            c.validate("config", config)

    def test_stable_object_id_and_version_changes(self):
        identity = examples()["catalog"]["entries"][0]["identity"]
        run = "11111111-1111-4111-8111-111111111111"
        key = c.digest(identity)
        self.assertEqual(key, "8808fd0dc3272eea187a7f934ba8ac066eadf31115df2c5da1943426bf75c239")
        self.assertEqual(c.object_id(run, key), "8638f2a8-a1cb-550f-aa65-860398c91393")
        self.assertEqual(c.object_id(run, key), c.object_id(run, key))
        for field, value in (("state", "archived"), ("profile", "portable-age-v1"),
                             ("source_sha256", "b" * 64)):
            self.assertNotEqual(key, c.digest({**identity, field: value}))
        changed = copy.deepcopy(identity)
        changed["fingerprint"]["recipients"] = ["synthetic-new-recipient"]
        self.assertNotEqual(key, c.digest(changed))
        self.assertNotEqual(c.object_id(run, key), c.object_id(str(uuid.uuid4()), key))

    def test_native_scrub_empty_complete_cross_source_and_oversize_rejected(self):
        config = examples()["config"]
        config["fingerprint"]["policy"] = "scrub"
        with self.assertRaises(ValueError):
            c.validate("config", config)
        catalog = examples()["catalog"]
        for change in ({"entries": []}, {"counts": {"eligible": 9, "succeeded": 9, "failed": 0, "excluded": 0}},
                       {"source_id": str(uuid.uuid4())}):
            with self.assertRaises(ValueError):
                c.validate("catalog", {**catalog, **change})
        catalog["entries"][0]["asset_bytes"] = c.MAX_OBJECT + 1
        with self.assertRaises(ValueError):
            c.validate("catalog", catalog)

    def test_opacity_outer_descriptor_no_native_uuid_title_or_path(self):
        allowed = set(c.SCHEMAS["object"]["properties"])
        self.assertTrue({"source_uuid", "title", "path", "version_key", "source_sha256"}.isdisjoint(allowed))
        self.assertEqual(backend.release_payload("cslb-v1-o-fixture", "main")["make_latest"], "false")

    def test_age_config_rejects_unprotected_or_incoherent_profiles(self):
        good = examples()["config"]
        for cipher, recipients, keyref in (("synthetic", [], "synthetic"),
                ("age-v1-x25519", [], good["key_reference"]),
                ("age-v1-x25519", good["fingerprint"]["recipients"], "/plaintext/private.key")):
            config = copy.deepcopy(good)
            config["fingerprint"].update(cipher=cipher, recipients=recipients)
            config["key_reference"] = keyref
            with self.assertRaises(ValueError):
                c.validate("config", config)

    def test_partial_without_failure_rejected(self):
        catalog = examples()["catalog"]
        catalog["status"] = "partial"
        with self.assertRaises(ValueError):
            c.validate("catalog", catalog)

    def test_container_member_bindings_layout_and_limits(self):
        for name in ("container", "layout"):
            good = examples()[name]
            c.validate(name, good)
            for mutation in ("empty", "duplicate", "path", "origin", "oversize"):
                bad = copy.deepcopy(good)
                if mutation == "empty":
                    bad["members"] = []
                elif mutation == "duplicate":
                    bad["members"] *= 2
                elif mutation == "path":
                    bad["members"][0]["path"] = "../unsafe.jsonl"
                elif mutation == "origin":
                    bad["members"][0]["origin"]["source_id"] = str(uuid.uuid4())
                else:
                    bad["members"][0]["bytes"] = c.MAX_OBJECT + 1
                with self.assertRaises(ValueError):
                    c.validate(name, bad)

    def test_final_ciphertext_boundaries_include_all_packaging_overhead(self):
        for size in (64*1024**2-1, 64*1024**2):
            c.validate_cipher_size(size, 2, "normal")
        with self.assertRaises(ValueError):
            c.validate_cipher_size(64*1024**2+1, 2, "normal")
        c.validate_cipher_size(c.MAX_OBJECT, 1, "oversized_single")
        for size, count in ((c.MAX_OBJECT+1, 1), (c.MAX_OBJECT, 2)):
            with self.assertRaises(ValueError):
                c.validate_cipher_size(size, count, "oversized_single")


class BackupLocalPrimitivesTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.control = GitControl(self.root / "control.git")

    def test_two_bootstraps_and_two_children_one_wins(self):
        parent, state = self.control.read()
        left = self.control.child(parent, {**state, "owner": "a"})
        right = self.control.child(parent, {**state, "owner": "b"})
        self.control.git("update-ref", self.control.ref, left, "0" * 40)
        result = self.control.git("update-ref", self.control.ref, right, "0" * 40, check=False)
        self.assertNotEqual(result.returncode, 0)
        parent, state = self.control.read()
        self.control.advance(parent, {**state, "intents": ["left"]})
        with self.assertRaises(Conflict):
            self.control.advance(parent, {**state, "intents": ["right"]})
        reread, state = self.control.read()
        self.control.advance(reread, {**state, "intents": state["intents"] + ["right"]})
        self.assertEqual(self.control.read()[1]["intents"], ["left", "right"])

    def test_lease_renewal_expiry_and_fencing_same_chain(self):
        _, epoch = self.control.acquire("a", 0)
        with self.assertRaises(Conflict):
            self.control.acquire("b", 5)
        self.control.mutate("a", epoch, 60, renew=True)
        with self.assertRaises(Conflict):
            self.control.acquire("b", 600)
        _, newer = self.control.acquire("b", 661)
        with self.assertRaises(Conflict):
            self.control.mutate("a", epoch, 662, checkpoint="stale")
        self.control.mutate("b", newer, 662, checkpoint="valid")
        self.assertEqual(self.control.read()[1]["latest"], "valid")
        with self.assertRaises(Conflict):
            self.control.mutate("b", newer, 1261, checkpoint="expired")

    def test_paused_prechecked_writer_cannot_commit_after_new_epoch(self):
        _, epoch = self.control.acquire("a", 0)
        checked_parent, checked_state = self.control.read()
        self.assertEqual(checked_state["epoch"], epoch)
        stale_child = self.control.child(checked_parent, {**checked_state, "latest": "STALE"})
        _, newer = self.control.acquire("b", 601)
        self.control.mutate("b", newer, 602, checkpoint="B")
        # Resume A after it checked but before it advanced the protected pointer.
        result = self.control.git("push", str(self.control.root), stale_child + ":" + self.control.ref, check=False)
        self.assertNotEqual(result.returncode, 0)
        with self.assertRaises(Conflict):
            self.control.mutate("a", epoch, 603, checkpoint="STALE")
        self.assertEqual(self.control.read()[1]["latest"], "B")

    def test_nonforce_git_push_rejects_divergent_children(self):
        # Unlike an in-memory CAS assertion, this executes Git's actual FF rule.
        parent, state = self.control.read()
        parent = self.control.advance(parent, state)
        first = self.control.child(parent, {**state, "owner": "a"})
        second = self.control.child(parent, {**state, "owner": "b"})
        destination = self.root / "destination.git"
        subprocess.run(["git", "init", "--bare", str(destination)], check=True, capture_output=True)
        self.control.git("push", str(destination), first + ":" + self.control.ref)
        result = self.control.git("push", str(destination), second + ":" + self.control.ref, check=False)
        self.assertNotEqual(result.returncode, 0)

    def test_lost_post_adopt_and_contradiction_never_overwrite(self):
        store = backend.SyntheticStore(self.root / "objects")
        oid = str(uuid.uuid4())
        with self.assertRaises(TimeoutError):
            store.publish(oid, b"synthetic original", lose_response=True)
        self.assertEqual(store.publish(oid, b"synthetic original"), b"synthetic original")
        with self.assertRaises(ValueError):
            store.publish(oid, b"contradiction")
        self.assertEqual(store.get(oid), b"synthetic original")

    def test_incomplete_asset_blocks_catalog_and_cold_restore(self):
        store = backend.SyntheticStore(self.root / "objects")
        oid, checkpoint = str(uuid.uuid4()), str(uuid.uuid4())
        content = b"synthetic content"
        entries = [{"object_id": oid, "sha256": hashlib.sha256(content).hexdigest()}]
        store.publish(oid, content, truncate=True)
        with self.assertRaises(ValueError):
            store.commit_catalog(checkpoint, entries)
        self.assertFalse((store.root / checkpoint).exists())
        good = str(uuid.uuid4())
        store.publish(good, content)
        entries[0]["object_id"] = good
        store.commit_catalog(checkpoint, entries)
        cold = backend.SyntheticStore(store.root)
        self.assertEqual(cold.cold_read(checkpoint), [content])
        self.assertGreater(len(cold.discover(page_size=1)), 1)

    def test_repository_rename_accepted_substitution_or_public_rejected(self):
        self.assertEqual(backend.check_repo(123, {"id": 123, "private": True, "full_name": "new/name"}), "new/name")
        for repo in ({"id": 456, "private": True}, {"id": 123, "private": False}):
            with self.assertRaises(ValueError):
                backend.check_repo(123, repo)
        for status in (403, 404, 429):
            self.assertNotEqual(backend.bounded_error(status), "not_found")


class BackupScaleTests(unittest.TestCase):
    def test_matrix_covers_every_requested_axis_deterministically(self):
        rows = scale.matrix()
        self.assertEqual(len(rows), 729)
        self.assertEqual(rows, scale.matrix())
        self.assertEqual({r["days"] for r in rows}, {30, 90, 365})
        self.assertTrue(any(r["exceeds_256MiB_object"] for r in rows))
        self.assertTrue(any(r["projected_exceeds_500_content_hourly_mean"] for r in rows))

    def test_small_scenario_counts_whole_versions_not_deltas(self):
        row = scale.scenario(100, 30, 65536, .01, 24, 0)
        self.assertEqual(row["objects"], 129)
        self.assertEqual(row["releases"], 159)
        self.assertEqual(row["assets"], 318)
        self.assertEqual(row["pre_restore_bytes"], 100 * (65536 + 2048))

    def test_containers_reduce_assets_not_just_release_count(self):
        alternative = scale.container_comparison()
        self.assertEqual(alternative["bootstrap"]["physical_containers"], 16)
        self.assertEqual(alternative["bootstrap"]["assets"], 34)
        self.assertEqual(alternative["bootstrap"]["writes_per_container_intent"], 127)
        self.assertEqual(alternative["incremental"]["physical_containers"], 2)
        self.assertEqual(alternative["incremental"]["writes_per_container_intent"], 29)


if __name__ == "__main__":
    unittest.main()
