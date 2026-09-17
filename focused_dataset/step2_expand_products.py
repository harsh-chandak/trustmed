import csv, time, sys, os, requests

BASE = "https://rxnav.nlm.nih.gov/REST"
S = requests.Session()
S.headers.update({"User-Agent": "trustmed-focus/1.0"})

SLEEP = 0.20

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

def rx_related_by_relas(rxcui, relas):
    out = []
    seen = set()
    for rel in relas:
        try:
            cps = rx_related_by_single_rela(rxcui, rel)
        except requests.HTTPError:
            continue
        for c in cps:
            key = (c.get("rxcui"), c.get("tty"))
            if key in seen: 
                continue
            seen.add(key); out.append(c)
    return out

def rx_allrelated(rxcui):
    j = _get(f"{BASE}/rxcui/{rxcui}/allrelated.json")
    return j.get("allRelatedGroup", {}).get("conceptGroup") or []

def pin_to_in(pin_rxcui):
    try:
        cps = rx_related_by_single_rela(pin_rxcui, "form_of")
    except requests.HTTPError:
        return []
    return [c for c in cps if c.get("tty") == "IN"]

def product_to_ingredients(product_rxcui):
    cps = rx_related_by_relas(product_rxcui, ["has_ingredient", "has_active_ingredient"])
    if not cps:
        groups = rx_allrelated(product_rxcui)
        for g in groups:
            if g.get("tty") in ("IN", "PIN"):
                cps.extend(g.get("conceptProperties") or [])

    ins = [c for c in cps if c.get("tty") == "IN"]
    pins = [c for c in cps if c.get("tty") == "PIN"]

    for p in pins:
        ins.extend(pin_to_in(p.get("rxcui")))

    seen, uniq = set(), []
    for c in ins:
        rx = c.get("rxcui")
        if rx and rx not in seen:
            seen.add(rx); uniq.append(c)
    return uniq

def get_products_for_ingredient(ing_rxcui):
    cps = rx_related_by_relas(ing_rxcui, ["ingredient_of", "active_ingredient_of"])
    prods = [c for c in cps if c.get("tty") in ("SCD", "SBD")]

    if not prods:
        groups = rx_allrelated(ing_rxcui)
        for g in groups:
            if g.get("tty") in ("SCD","SBD"):
                prods.extend(g.get("conceptProperties") or [])

    seen, out = set(), []
    for p in prods:
        k = (p.get("rxcui"), p.get("tty"))
        if None in k or k in seen: 
            continue
        seen.add(k); out.append(p)
    return out

def read_ingredients(path="ingredients.csv"):
    out = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("tty") == "IN" and r.get("rxcui"):
                out.append({"rxcui": r["rxcui"], "name": r.get("name", "")})
    return out

def dedupe(rows, keys):
    seen, out = set(), []
    for r in rows:
        k = tuple(r[k] for k in keys)
        if None in k or k in seen:
            continue
        seen.add(k); out.append(r)
    return out

def main(in_csv="ingredients.csv",
         out_products="products.csv",
         out_pairs="product_ingredient.csv",
         max_products_per_ing=None):
    os.makedirs(".", exist_ok=True)

    ingredients = read_ingredients(in_csv)
    print(f"[info] loaded {len(ingredients)} ingredients from {in_csv}")

    product_rows = []
    pair_rows = []

    for i, ing in enumerate(ingredients, 1):
        ing_rx, ing_name = ing["rxcui"], ing["name"]
        print(f"[info] ({i}/{len(ingredients)}) {ing_name} [{ig_rx if (ig_rx:=ing_rx) else ''}] → products")

        try:
            prods = get_products_for_ingredient(ing_rx)
        except requests.HTTPError as e:
            print(f"[warn]   ingredient→products failed for {ing_rx}: {e}")
            prods = []

        if max_products_per_ing and len(prods) > max_products_per_ing:
            prods = prods[:max_products_per_ing]

        for p in prods:
            prx = p.get("rxcui"); pname = p.get("name"); ptty = p.get("tty")
            if not prx or ptty not in ("SCD","SBD"):
                continue

            product_rows.append({
                "product_rxcui": prx,
                "product_name": pname,
                "tty": ptty
            })

            try:
                ins = product_to_ingredients(prx)
            except requests.HTTPError as e:
                print(f"[warn]   product→ingredients failed for {prx}: {e}")
                ins = []

            for c in ins:
                in_rx = c.get("rxcui")
                if in_rx:
                    pair_rows.append({
                        "product_rxcui": prx,
                        "ingredient_rxcui": in_rx
                    })

        time.sleep(SLEEP)

    product_rows = dedupe(product_rows, ("product_rxcui","tty"))
    pair_rows = dedupe(pair_rows, ("product_rxcui","ingredient_rxcui"))

    with open(out_products, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["product_rxcui","product_name","tty"])
        w.writeheader(); w.writerows(product_rows)
    with open(out_pairs, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["product_rxcui","ingredient_rxcui"])
        w.writeheader(); w.writerows(pair_rows)

    print(f"[done] wrote {len(product_rows)} rows to {out_products}")
    print(f"[done] wrote {len(pair_rows)} rows to {out_pairs}")

if __name__ == "__main__":
    argv = sys.argv[1:]
    in_csv = argv[0] if len(argv) >= 1 else "ingredients.csv"
    out_products = argv[1] if len(argv) >= 2 else "products.csv"
    out_pairs = argv[2] if len(argv) >= 3 else "product_ingredient.csv"
    max_per = int(argv[3]) if len(argv) >= 4 else None
    main(in_csv, out_products, out_pairs, max_per)
