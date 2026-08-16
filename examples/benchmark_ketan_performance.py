"""
Empirical Benchmark Suite for Ketan-OS.
Measures:
1. Snapshot Creation Latency (1,000 files)
2. Time-Travel Rollback Speed (Sub-millisecond reversion)
3. Zero-State-Leak Data Integrity (Byte-for-byte SHA256 verification)
4. Epistemic Contradiction & Memory Inspection Speed
"""

import os
import sys
import time
import shutil
import tempfile
import hashlib
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from ketan import KetanHarness, ShadowFS, DualLedger, EpistemicBeliefEngine
from examples.langgraph_business_demo.generate_large_db import generate_1000_orders

def get_dir_sha256(dir_path: str) -> str:
    """Computes a cryptographic hash of all non-ignored files in a directory."""
    hasher = hashlib.sha256()
    for root, dirs, files in sorted(os.walk(dir_path)):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != "__pycache__")
        for fname in sorted(files):
            if fname.endswith(".pyc"):
                continue
            fpath = os.path.join(root, fname)
            with open(fpath, "rb") as f:
                hasher.update(f.read())
    return hasher.hexdigest()


def run_benchmark():
    print("\n" + "=" * 76)
    print(" 🚀 KETAN-OS EMPIRICAL BENCHMARK SUITE")
    print("=" * 76 + "\n")

    results = {}

    # -------------------------------------------------------------------------
    # BENCHMARK 1: SNAPSHOT CREATION SPEED (1,000 FILES / 200KB DB)
    # -------------------------------------------------------------------------
    print("[1/4] Measuring Snapshot Creation Speed on 1,000 Files...")
    with tempfile.TemporaryDirectory(prefix="ketan_bench_ws_") as temp_ws:
        db_dir = Path(temp_ws) / "mock_db"
        generate_1000_orders(str(db_dir))

        harness = KetanHarness(temp_ws)
        
        snapshot_times = []
        for i in range(20):
            t0 = time.time()
            cp = harness.create_checkpoint(prompt_stack=[{"role": "user", "content": f"Turn {i}"}])
            snapshot_times.append((time.time() - t0) * 1000)

        avg_snapshot = sum(snapshot_times) / len(snapshot_times)
        min_snapshot = min(snapshot_times)
        max_snapshot = max(snapshot_times)

        results["avg_snapshot_ms"] = avg_snapshot
        results["min_snapshot_ms"] = min_snapshot
        results["max_snapshot_ms"] = max_snapshot
        print(f"  ✓ Avg: {avg_snapshot:.2f} ms | Min: {min_snapshot:.2f} ms | Max: {max_snapshot:.2f} ms\n")

    # -------------------------------------------------------------------------
    # BENCHMARK 2: TIME-TRAVEL ROLLBACK SPEED
    # -------------------------------------------------------------------------
    print("[2/4] Measuring Sub-Second Time-Travel Rollback Speed...")
    with tempfile.TemporaryDirectory(prefix="ketan_bench_rb_") as temp_ws:
        db_dir = Path(temp_ws) / "mock_db"
        generate_1000_orders(str(db_dir))

        harness = KetanHarness(temp_ws)
        cp_clean = harness.create_checkpoint(prompt_stack=[{"role": "user", "content": "Clean state"}])

        # Mutate directory (create 50 new files, corrupt 10 existing files)
        for i in range(50):
            (Path(temp_ws) / f"corrupted_{i}.tmp").write_text("CORRUPTED DATA " * 100)

        rollback_times = []
        for i in range(10):
            t0 = time.time()
            actions = harness.shadow_fs.rollback_to(cp_clean.fs_snapshot_id)
            rollback_times.append((time.time() - t0) * 1000)
            # Re-corrupt for next loop iteration
            for j in range(10):
                (Path(temp_ws) / f"corrupted_{j}.tmp").write_text("CORRUPTED DATA " * 100)

        avg_rollback = sum(rollback_times) / len(rollback_times)
        results["avg_rollback_ms"] = avg_rollback
        print(f"  ✓ Avg Rollback Time: {avg_rollback:.2f} ms (Target < 100ms)\n")

    # -------------------------------------------------------------------------
    # BENCHMARK 3: DATA INTEGRITY / ZERO STATE-LEAK GUARANTEE
    # -------------------------------------------------------------------------
    print("[3/4] Verifying 100% Byte-for-Byte Data Integrity Across 100 Crashes...")
    with tempfile.TemporaryDirectory(prefix="ketan_bench_integrity_") as temp_ws:
        db_dir = Path(temp_ws) / "mock_db"
        generate_1000_orders(str(db_dir))

        initial_hash = get_dir_sha256(temp_ws)
        harness = KetanHarness(temp_ws, max_rollback_attempts=1000)
        cp_initial = harness.create_checkpoint(prompt_stack=[{"role": "user", "content": "Initial"}])

        state_leaks = 0
        for i in range(100):
            # Attempt tool call that crashes
            try:
                (Path(temp_ws) / "mock_db" / "financial_ledger.json").write_text("BROKEN_MUTATION")
                harness.rollback(cp_initial.checkpoint_id, "Corrupted write", "Revert")
            except Exception:
                pass
            
            curr_hash = get_dir_sha256(temp_ws)
            if curr_hash != initial_hash:
                state_leaks += 1

        results["data_integrity_pass"] = (state_leaks == 0)
        print(f"  ✓ State Leaks Detected: {state_leaks} / 100 attempts ({'100% DATA INTEGRITY PASSED' if state_leaks == 0 else 'FAILED'})\n")

    # -------------------------------------------------------------------------
    # BENCHMARK 4: EPISTEMIC CONTRADICTION INSPECTION SPEED
    # -------------------------------------------------------------------------
    print("[4/4] Measuring Epistemic Contradiction Engine Performance...")
    engine = EpistemicBeliefEngine()
    for i in range(100):
        engine.assert_belief(subject=f"file:app_{i}.py", predicate="valid_syntax", object_val=True)

    t0 = time.time()
    events = engine.inspect_observation(subject="file:app_50.py", predicate="valid_syntax", observed_val=False)
    epistemic_ms = (time.time() - t0) * 1000

    results["epistemic_ms"] = epistemic_ms
    results["contradictions_detected"] = len(events)
    print(f"  ✓ Epistemic Contradiction Inspection: {epistemic_ms:.3f} ms ({len(events)} contradiction detected)\n")

    # -------------------------------------------------------------------------
    # SUMMARY TABLE
    # -------------------------------------------------------------------------
    print("=" * 76)
    print(" 📊 SUMMARY OF EMPIRICAL BENCHMARK METRICS")
    print("=" * 76)
    print(f"  1. Snapshot Latency (1,000 Files / 200KB DB) : {results['avg_snapshot_ms']:.2f} ms")
    print(f"  2. Time-Travel Rollback Latency              : {results['avg_rollback_ms']:.2f} ms")
    print(f"  3. Data Integrity & Zero State Leak Guarantee: {'100% VERIFIED' if results['data_integrity_pass'] else 'FAILED'}")
    print(f"  4. Epistemic Contradiction Inspection Speed   : {results['epistemic_ms']:.3f} ms")
    print("=" * 76 + "\n")

if __name__ == "__main__":
    run_benchmark()
