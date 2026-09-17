import csv, sys, time, requests

BASE = "https://rxnav.nlm.nih.gov/REST"
S = requests.Session()
S.headers.update({"User-Agent": "trustmed-focus/1.0"})

CLASS_IDS = ["C09AA","C09BA"]

def _get(url, params=None):
    r = S.get(url, params=params, timeout=25)
    r.raise_for_status()
    return r.json()

def class_members_all_ttys(class_id):
    j = _get(f"{BASE}/rxclass/classMembers.json", {"classId": class_id, "relaSource": "ATC"})
    return (j.get("rxclassdata",{}).get("drugMemberGroup",{}).get("drugMember") or [])

def related(rxcui, rela_query):
    j = _get(f"{BASE}/rxcui/{rxcui}/related.json", {"rela": rela_query})
    groups = j.get("relatedGroup",{}).get("conceptGroup") or []
    out=[]
    for g in groups:
        for c in g.get("conceptProperties",[]) or []:
            out.append(c)
    return out

def normalize_to_in(rxcui, tty):
    if tty == "IN":
        return [{"rxcui": rxcui, "name": None, "tty": "IN"}]

    if tty == "PIN":
        cps = related(rxcui, "form_of")  # PIN form_of IN
        return [c for c in cps if c.get("tty")=="IN"] or []

    cps = related(rxcui, "has_ingredient+has_active_ingredient")
    ins=[]
    pins=[c for c in cps if c.get("tty")=="PIN"]
    ins.extend([c for c in cps if c.get("tty")=="IN"])
    for p in pins:
        ins.extend([c for c in related(p["rxcui"], "form_of") if c.get("tty")=="IN"])

    seen=set(); uniq=[]
    for c in ins:
        rx=c.get("rxcui"); 
        if rx and rx not in seen:
            seen.add(rx); uniq.append(c)
    return uniq

def main(out_csv="ingredients.csv"):
    seen=set()
    rows=[]
    for cid in CLASS_IDS:
        members = class_members_all_ttys(cid)
        print(f"[info] {cid}: {len(members)} total members")
        for m in members:
            mc = m.get("minConcept") or {}
            rx, name, tty = mc.get("rxcui"), mc.get("name"), mc.get("tty")
            if not rx or not tty: 
                continue
            ins = normalize_to_in(rx, tty)
            for c in ins:
                in_rx = c.get("rxcui") or rx
                in_name = c.get("name")
                key = (in_rx, "IN")
                if key in seen: 
                    continue
                seen.add(key)
                rows.append({
                    "rxcui": in_rx,
                    "name": (in_name or name or "unknown").lower(),
                    "tty": "IN",
                    "source_class": f"ATC:{cid}",
                    "source_class_id": cid
                })
        time.sleep(0.2)
    rows.sort(key=lambda r: r["name"])
    with open(out_csv,"w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=["rxcui","name","tty","source_class","source_class_id"])
        w.writeheader(); w.writerows(rows)
    print(f"[done] wrote {len(rows)} rows to {out_csv}")

if __name__=="__main__":
    out=sys.argv[1] if len(sys.argv)>1 else "ingredients.csv"
    main(out)
