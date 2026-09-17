import csv, os, sys, time, requests, urllib.parse

S = requests.Session()
S.headers.update({"User-Agent":"trustmed-focus/1.0"})
BASE = "https://api.fda.gov/drug/label.json"

def fetch_label_id(brand):
    q = f'openfda.brand_name:"{brand}"'
    try:
        r = S.get(BASE, params={"search": q, "limit": 1}, timeout=25)
        r.raise_for_status()
        j = r.json()
        if j.get("results"):
            return j["results"][0].get("id")
    except Exception:
        return None
    return None

def main(in_csv="brand_generic.csv", out_csv="evidence.csv", max_rows=100):
    rows=[]
    with open(in_csv, newline="", encoding="utf-8") as f:
        data=list(csv.DictReader(f))

    data=data[:max_rows] if max_rows else data
    for r in data:
        brand = r.get("brand_name") or ""
        if not brand:
            continue
        evid = fetch_label_id(brand)
        rows.append({
            "entity_type":"brand",
            "key_rxcui": r.get("brand_rxcui") or "",
            "key_text": brand,
            "source":"openFDA",
            "pointer": evid or "n/a"
        })
        time.sleep(0.15)

    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w=csv.DictWriter(f, fieldnames=["entity_type","key_rxcui","key_text","source","pointer"])
        w.writeheader(); w.writerows(rows)
    print(f"[done] wrote {len(rows)} rows to {out_csv}")

if __name__=="__main__":
    argv=sys.argv[1:]
    in_csv = argv[0] if len(argv)>=1 else "brand_generic.csv"
    out_csv = argv[1] if len(argv)>=2 else "evidence.csv"
    max_rows = int(argv[2]) if len(argv)>=3 else 100
    main(in_csv, out_csv, max_rows)

