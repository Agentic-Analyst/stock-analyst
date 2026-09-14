import json, re
raw = open("/tmp/sweep20.out").read()
m = re.search(r'^\s*\[', raw, re.M)
rows = json.loads(raw[m.start():]) if m else []
print("%-7s%-9s%-8s%-7s%-11s%-11s%-9s%-22s" % ("TICKER","STATUS","INTEG","ISSUE","PRICE","MIDPOINT","GAP%","METHOD"))
print("-"*86)
pub = wit = 0
gaps = []
for r in rows:
    lo, hi, px = r.get("range_low"), r.get("range_high"), r.get("current_price")
    mid = (lo+hi)/2 if isinstance(lo,(int,float)) and isinstance(hi,(int,float)) else None
    gap = ((mid-px)/px*100) if mid and isinstance(px,(int,float)) and px else None
    if gap is not None: gaps.append(gap)
    w = r.get("point_estimate_withheld")
    wit += 1 if w else 0
    pub += 0 if w else 1
    print("%-7s%-9s%-8s%-7s%-11s%-11s%-9s%-22s" % (
        r.get("ticker"), r.get("status"), r.get("model_integrity_status"),
        r.get("model_integrity_issue_count"),
        ("%.2f"%px) if isinstance(px,(int,float)) else "-",
        ("%.2f"%mid) if mid else "-",
        ("%+.1f"%gap) if gap is not None else "-",
        str(r.get("method"))[:20]))
print()
print("  TOTAL %d | withheld %d | PUBLISHED %d" % (len(rows), wit, pub))
if gaps:
    gaps.sort()
    print("  gap vs market: median %+.1f%%  min %+.1f%%  max %+.1f%%  below-market %d/%d" % (
        gaps[len(gaps)//2], gaps[0], gaps[-1], sum(1 for g in gaps if g<0), len(gaps)))
