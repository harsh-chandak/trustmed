import csv, os, sys, time, requests

BASE = "https://rxnav.nlm.nih.gov/REST"
S = requests.Session()
S.headers.update({"User-Agent": "trustmed-focus/1.0"})
SLEEP = 0.2

def _get(url, params=None):
    r = S.get(url, params=params, timeout=25)
    r.raise_for_status()
    return r.json()

def rx_related_by_single_rela(rxcui, rela):
    j = _get(f"{BASE}/rxcui/{rxcui}/related.json", {"rela": rela})
    groups = j.get("relatedGroup", {}).get("conceptGroup") or []
    out = []
    for g in groups:
        out.extend(g.get("conceptProperties") or [])
    return out

def rx_related_all(rxcui):
    j = _get(f"{BASE}/rxcui/{rxcui}/allrelated.json")
    return j.get("allRelatedGroup", {}).get("conceptGroup") or []

def pin_to_in(pin_rxcui):
    try:
        cps = rx_related_by_single_rela(pin_rxcui, "form_of")
    except requests.HTTPError:
        return []
    return [c for c in cps if c.get("tty") == "IN"]

def product_to_ingredients(product_rxcui):
    ins = []
    seen = set()

    for rel in ("has_ingredient", "has_active_ingredient"):
        try:
            cps = rx_related_by_single_rela(product_rxcui, rel)
        except requests.HTTPError:
            cps = []
        for c in cps:
            if c.get("tty") in ("IN", "PIN"):
                key = (c.get("rxcui"), c.get("tty"))
                if key not in seen:
                    seen.add(key); ins.append(c)

    if not ins:
        groups = rx_related_all(product_rxcui)
        for g in groups:
            if g.get("tty") in ("IN","PIN"):
                for c in g.get("conceptProperties") or []:
                    key = (c.get("rxcui"), c.get("tty"))
                    if key not in seen:
                        seen.add(key); ins.append(c)

    outs = [c for c in ins if c.get("tty") == "IN"]
    for c in ins:
        if c.get("tty") == "PIN":
            outs.extend(pin_to_in(c.get("rxcui")))

    uniq, seen2 = [], set()
    for c in outs:
        rx = c.get("rxcui")
        if rx and rx not in seen2:
            seen2.add(rx); uniq.append(c)
    return uniq

def sbd_to_scd(sbd_rxcui):
    try:
        cps = rx_related_by_single_rela(sbd_rxcui, "tradename_of")
        for c in cps:
            if c.get("tty") == "SCD":
                return c.get("rxcui")
    except requests.HTTPError:
        pass

    groups = rx_related_all(sbd_rxcui)
    for g in groups:
        if g.get("tty") == "SCD":
            props = g.get("conceptProperties") or []
            return props[0].get("rxcui") if props else None
    return None

def sbd_to_bn(sbd_rxcui):
    bns = []
    groups = rx_related_all(sbd_rxcui)
    for g in groups:
        if g.get("tty") == "BN":
            bns.extend(g.get("conceptProperties") or [])
    
    out, seen = [], set()
    for b in bns:
        rx = b.get("rxcui")
        if rx and rx not in seen:
            seen.add(rx); out.append(b)
    return out

def read_products(path="products.csv"):
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("tty") == "SBD" and r.get("product_rxcui"):
                rows.append({"sbd_rxcui": r["product_rxcui"], "product_name": r.get("product_name", "")})
    return rows

def main(in_products="products.csv", out_csv="brand_generic.csv", max_sbd=None):
    os.makedirs(".", exist_ok=True)
    sbds = read_products(in_products)
    print(f"[info] loaded {len(sbds)} SBD rows from {in_products}")

    if max_sbd and len(sbds) > max_sbd:
        sbds = sbds[:max_sbd]
        print(f"[info] limiting to first {len(sbds)} SBDs")

    rows = []
    for i, s in enumerate(sbds, 1):
        sbd = s["sbd_rxcui"]; pname = s["product_name"]
        print(f"[info] ({i}/{len(sbds)}) SBD {pname} [{sbd}]")
        
        try:
            bns = sbd_to_bn(sbd)
        except requests.HTTPError as e:
            print(f"[warn]   BN lookup failed for {sbd}: {e}")
            bns = []

        scd = None
        try:
            scd = sbd_to_scd(sbd)
        except requests.HTTPError as e:
            print(f"[warn]   SCD lookup failed for {sbd}: {e}")

        try:
            ins = product_to_ingredients(sbd)
        except requests.HTTPError as e:
            print(f"[warn]   IN lookup failed for {sbd}: {e}")
            ins = []

        if not bns:
            bns = [{"rxcui": None, "name": pname, "tty": "BN"}]

        for bn in bns:
            bn_rx = bn.get("rxcui")
            bn_name = bn.get("name")
            for ing in ins:
                rows.append({
                    "brand_rxcui": bn_rx or "",
                    "brand_name": bn_name or "",
                    "ingredient_rxcui": ing.get("rxcui") or "",
                    "ingredient_name": (ing.get("name") or "").lower(),
                    "sbd_rxcui": sbd,
                    "scd_rxcui": scd or ""
                })

        time.sleep(SLEEP)

    
    seen, out = set(), []
    for r in rows:
        k = (r["brand_name"].lower(), r["ingredient_rxcui"], r["sbd_rxcui"])
        if k in seen: 
            continue
        seen.add(k); out.append(r)

    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "brand_rxcui","brand_name","ingredient_rxcui","ingredient_name","sbd_rxcui","scd_rxcui"
        ])
        w.writeheader(); w.writerows(out)
    print(f"[done] wrote {len(out)} rows to {out_csv}")

if __name__ == "__main__":
    argv = sys.argv[1:]
    in_products = argv[0] if len(argv) >= 1 else "products.csv"
    out_csv = argv[1] if len(argv) >= 2 else "brand_generic.csv"
    max_sbd = int(argv[2]) if len(argv) >= 3 else None
    main(in_products, out_csv, max_sbd)
