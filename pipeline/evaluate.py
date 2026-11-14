"""Score resolution against the hidden answer key. The key is never used by the pipeline itself."""
import csv
from collections import defaultdict
from itertools import combinations


def evaluate(recs, people, key_path):
    truth = {}
    with open(key_path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            truth[f"{r['source']}:{r['record_id']}"] = r

    # --- junk detection ---
    is_junk_true = {rid: t["person_id"] in ("JUNK", "SPAM") for rid, t in truth.items()}
    flagged = {r["rid"] for r in recs if r["junk"]}
    tp = sum(1 for rid in flagged if is_junk_true[rid])
    fp = len(flagged) - tp
    fn = sum(1 for rid, j in is_junk_true.items() if j and rid not in flagged)

    # --- person clustering (pairwise) ---
    pred_cluster = {}
    for i, p in enumerate(people):
        for rid in p["rids"]:
            pred_cluster[rid] = i
    rids = [rid for rid in pred_cluster if not is_junk_true[rid]]
    true_pairs, pred_pairs = set(), set()
    by_true, by_pred = defaultdict(list), defaultdict(list)
    for rid in rids:
        by_true[truth[rid]["person_id"]].append(rid)
        by_pred[pred_cluster[rid]].append(rid)
    for group in by_true.values():
        true_pairs.update(tuple(sorted(x)) for x in combinations(group, 2))
    for group in by_pred.values():
        pred_pairs.update(tuple(sorted(x)) for x in combinations(group, 2))
    ptp = len(true_pairs & pred_pairs)
    precision = ptp / len(pred_pairs) if pred_pairs else 1.0
    recall = ptp / len(true_pairs) if true_pairs else 1.0

    missed = sorted(true_pairs - pred_pairs)
    wrong = sorted(pred_pairs - true_pairs)

    # --- company assignment per record ---
    rec_by_id = {r["rid"]: r for r in recs}
    person_company = {}
    for p in people:
        for rid in p["rids"]:
            person_company[rid] = p["company_domain"]
    correct = assigned_wrong = unassigned = 0
    for rid in rids:
        want = truth[rid]["domain"] or None
        got = person_company.get(rid)
        if got == want:
            correct += 1
        elif got is None:
            unassigned += 1
        else:
            assigned_wrong += 1

    true_people = len({truth[r]["person_id"] for r in rids})
    return {
        "records": len(truth),
        "junk": {"flagged": len(flagged), "true_positive": tp, "false_positive": fp, "missed": fn},
        "people": {"true_people": true_people, "predicted_people": len(people),
                   "pair_precision": round(precision, 3), "pair_recall": round(recall, 3),
                   "missed_merges": len(missed), "wrong_merges": len(wrong)},
        "company": {"correct": correct, "wrong": assigned_wrong, "unassigned": unassigned,
                    "accuracy": round(correct / len(rids), 3)},
        "_missed_examples": [(rec_by_id[a]["email_raw"].strip(), rec_by_id[b]["email_raw"].strip()) for a, b in missed[:8]],
        "_wrong_examples": [(rec_by_id[a]["email_raw"].strip(), rec_by_id[b]["email_raw"].strip()) for a, b in wrong[:8]],
    }
