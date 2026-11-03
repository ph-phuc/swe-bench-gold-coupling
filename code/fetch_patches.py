"""(Release copy of the run's index_predictions.py; only ROOT differs. Agent patches are not redistributed in this
release: run this to fetch them from their public source, then match them to data/labels/entries.csv by sha256 of
the patch text.)

Index the passing patches of every SWE-bench Verified leaderboard entry (github.com/SWE-bench/experiments).

For each entry: `results/results.json` gives the instances it resolved on the original tests; the patch that was
evaluated is `logs/<instance_id>/patch.diff` under the entry's `assets` (the public S3 bucket for older entries, the
submitter's GitHub repo for newer ones). Stdlib only; resumable (raw patches are cached under data/raw/).

    python code/fetch_patches.py [--workers 16] [--limit-systems N]

Writes data/passing_index.jsonl (system, instance_id, sha), data/passing_patches/<instance_id>.jsonl
(system, sha, model_patch) and data/index_report.json (per entry: resolved, fetched, failed).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]   # the release root
DATA = ROOT / "data"
API = "https://api.github.com/repos/SWE-bench/experiments/contents/evaluation/verified"
RAW = "https://raw.githubusercontent.com/SWE-bench/experiments/main/evaluation/verified"
S3 = "https://swe-bench-submissions.s3.amazonaws.com/"
UA = {"User-Agent": "swe-abs-census-fetch"}


def get(url: str, tries: int = 4) -> bytes | None:
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):  # S3 answers 403 for a missing key
                return None
            time.sleep(2 ** i)
        except Exception:  # URLError, timeouts, IncompleteRead, SSLError: retry, never abort the run
            time.sleep(2 ** i)
    return None


def logs_base(metadata: str) -> str | None:
    """HTTP base under which `<instance_id>/patch.diff` lives, from metadata.yaml's assets block."""
    logs = re.search(r"^\s+logs:\s*(\S+)", metadata, re.M)
    repo = re.search(r"^\s+repo:\s*(\S+)", metadata, re.M)
    if logs and logs.group(1).startswith("s3://swe-bench-submissions/"):
        return S3 + logs.group(1)[len("s3://swe-bench-submissions/"):].rstrip("/")
    if repo:
        m = re.match(r"https://github.com/([^/]+)/([^/]+?)(?:\.git)?/?$", repo.group(1))
        if m:
            return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/HEAD/logs"
    return None


_entry_preds: dict[str, dict] = {}
_entry_lock = threading.Lock()


def entry_preds(base: str) -> dict:
    """{instance_id: model_patch} from the entry-level predictions file beside `logs/` (older entries keep one
    .eval.log per task and no patch.diff). Fetched once per entry."""
    root = base.rsplit("/logs", 1)[0]
    with _entry_lock:
        if root in _entry_preds:
            return _entry_preds[root]
        preds = {}
        for name in ("all_preds.jsonl", "preds.json"):
            body = get(f"{root}/{name}")
            if not body:
                continue
            text = body.decode("utf-8", errors="replace")
            try:
                obj = json.loads(text)
                if isinstance(obj, dict) and "instance_id" in obj:  # a one-line JSONL file
                    obj = [obj]
                if isinstance(obj, dict):  # {iid: row} or {iid: "patch"}
                    rows = [v if isinstance(v, dict) else {"instance_id": k, "model_patch": v} for k, v in obj.items()]
                else:
                    rows = obj
            except json.JSONDecodeError:
                rows = []
                for line in text.splitlines():
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue  # one bad line must not abort the run
            preds = {r["instance_id"]: r.get("model_patch") or "" for r in rows
                     if isinstance(r, dict) and "instance_id" in r and isinstance(r.get("model_patch") or "", str)}
            break
        _entry_preds[root] = preds
        return preds


def fetch_patch(base: str, system: str, iid: str) -> str | None:
    cache = DATA / "raw" / system / f"{iid}.diff"
    if cache.exists():  # bytes, so CRLF in a patch survives a resumed run unchanged
        return cache.read_bytes().decode("utf-8", errors="replace")
    body = get(f"{base}/{iid}/patch.diff")
    if body is None:
        patch = entry_preds(base).get(iid)
        if not patch:
            return None
        body = patch.encode("utf-8", errors="replace")  # a lone surrogate from a JSON escape must not raise
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(body)
    return body.decode("utf-8", errors="replace")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--limit-systems", type=int, default=0)
    a = ap.parse_args()

    listing = json.loads(get(API) or b"[]")
    systems = sorted(x["name"] for x in listing if x.get("type") == "dir")
    if a.limit_systems:
        systems = systems[: a.limit_systems]
    print(f"{len(systems)} Verified entries", flush=True)

    report, jobs = {}, []
    for s in systems:
        meta = (get(f"{RAW}/{s}/metadata.yaml") or b"").decode("utf-8", errors="replace")
        res = get(f"{RAW}/{s}/results/results.json")
        resolved = json.loads(res).get("resolved", []) if res else []
        if res is None:  # newer entries list per-task outcomes in per_instance_details.json instead
            det = get(f"{RAW}/{s}/per_instance_details.json")
            if det:
                resolved = sorted(i for i, v in json.loads(det).items() if isinstance(v, dict) and v.get("resolved"))
        base = logs_base(meta)
        report[s] = {"resolved": len(resolved), "logs_base": base, "fetched": 0, "failed": [],
                     "no_results_json": res is None}
        if base:
            jobs += [(s, base, iid) for iid in resolved]
    print(f"{len(jobs)} resolved (entry, instance) pairs to fetch", flush=True)

    def work(job):
        s, base, iid = job
        return s, iid, fetch_patch(base, s, iid)

    by_task = defaultdict(list)
    index = []
    with ThreadPoolExecutor(a.workers) as ex:
        for n, (s, iid, patch) in enumerate(ex.map(work, jobs), 1):
            if not patch or not patch.strip():
                report[s]["failed"].append(iid)
            else:
                sha = hashlib.sha256(patch.encode("utf-8")).hexdigest()
                report[s]["fetched"] += 1
                index.append({"system": s, "instance_id": iid, "sha": sha})
                by_task[iid].append({"system": s, "sha": sha, "model_patch": patch})
            if n % 1000 == 0:
                print(f"  {n}/{len(jobs)}", flush=True)

    out = DATA / "passing_patches"
    out.mkdir(parents=True, exist_ok=True)
    for iid, rows in by_task.items():
        (out / f"{iid}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    (DATA / "passing_index.jsonl").write_text("".join(json.dumps(r) + "\n" for r in index), encoding="utf-8")
    (DATA / "index_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    unique = len({(r["instance_id"], r["sha"]) for r in index})
    nobase = [s for s, r in report.items() if not r["logs_base"]]
    nores = [s for s, r in report.items() if r["no_results_json"]]
    print(f"indexed {len(index)} passing patches ({unique} unique per task) over {len(by_task)} tasks; "
          f"failed {sum(len(r['failed']) for r in report.values())}; entries without assets: {len(nobase)}; "
          f"without results.json: {len(nores)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
