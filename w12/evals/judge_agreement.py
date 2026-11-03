"""Judge vs hand labels, as a number.

    python -m w12.evals.judge_agreement evals/w12/runs/<label>

Week 6 validated a *summary* judge (92% vs labels) but no code ever computed
the number, and the claims judge (judge_v1) never had one. This computes it:
agreement = items where the judge's verdict equals the hand label, over
items that carry a hand label. Unlabelled items are counted and reported,
never imputed -- a judge agreement number is only as real as the labels
behind it, and a missing label is not a "pass".
"""

import json
import sys
from pathlib import Path

BAR = 0.85


def compute(run_dir, rows=None):
    run_dir = Path(run_dir)
    labels_path, judge_path = run_dir / "labels.json", run_dir / "judge.json"
    judged = json.loads(judge_path.read_text()) if judge_path.exists() else {}
    items = json.loads(labels_path.read_text())["items"] if labels_path.exists() else []
    if rows is not None:
        live = {r["trace_id"] for r in rows}
        items = [i for i in items if i["trace_id"] in live]
        total = len(rows)
    else:
        total = len(items)
    labelled = [i for i in items if i.get("label") in ("pass", "fail") and judged.get(i["trace_id"], {}).get("verdict")]
    agree = [i for i in labelled if judged[i["trace_id"]]["verdict"] == i["label"]]
    out = {"labelled": len(labelled), "total": total, "agree": len(agree), "bar": BAR,
           "labellers": sorted({i.get("labeller") or "?" for i in labelled}),
           "disagreements": [{"case": i["case"], "trace_id": i["trace_id"], "label": i["label"],
                              "judge": judged[i["trace_id"]]["verdict"]} for i in labelled if i not in agree]}
    if not labelled:
        out["agreement"] = None
        out["summary"] = (f"UNLABELLED {total}/{total} -- no agreement number yet. Fill labels.json in the run "
                          f"directory (blind to judge.json), then rescore.")
    else:
        out["agreement"] = round(len(agree) / len(labelled), 3)
        verdict = "clears" if out["agreement"] >= BAR else "DOES NOT clear"
        out["summary"] = (f"{out['agreement']:.1%} ({len(agree)}/{len(labelled)} labelled items; "
                          f"{total - len(labelled)} unlabelled) -- {verdict} the {BAR:.0%} bar. "
                          f"Labeller(s): {', '.join(out['labellers'])}.")
    return out


if __name__ == "__main__":
    print(json.dumps(compute(sys.argv[1]), indent=1))
