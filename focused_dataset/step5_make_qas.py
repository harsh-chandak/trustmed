import csv, json, random, os
random.seed(42)

ING_F = "ingredients.csv"
PROD_F = "products.csv"
PAIR_F = "product_ingredient.csv"
BG_F   = "brand_generic.csv"

OUT_QA = "qas.jsonl"

def load_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def main():
    ings   = load_csv(ING_F)                       
    prods  = load_csv(PROD_F)                      
    pairs  = load_csv(PAIR_F)                      
    bgn    = load_csv(BG_F)                        
    
    ing_name_by_rx = {r["rxcui"]: r["name"].lower() for r in ings}
    prod_name_by_rx= {r["product_rxcui"]: r["product_name"] for r in prods}
    ing_products = {}  
    for r in pairs:
        ing_products.setdefault(r["ingredient_rxcui"], set()).add(r["product_rxcui"])

    qas = []

    seen_bg = set()
    for r in bgn:
        brand = r["brand_name"].strip()
        ing   = (r["ingredient_name"] or "").lower().strip()
        if not brand or not ing:
            continue
        key = (brand.lower(), ing)
        if key in seen_bg: 
            continue
        seen_bg.add(key)
        qas.append({
            "q": f"what is the generic for {brand}?",
            "intent": "brand_to_generic",
            "brand_name": brand,
            "answer": [ing],
            "split": "test"
        })


    prod_candidates = [p for p in prods if "/" in p["product_name"]] + \
                      [p for p in prods if "/" not in p["product_name"]]
    taken = 0
    for p in prod_candidates:
        if taken >= 40: break
        prx = p["product_rxcui"]; pname = p["product_name"]
        ing_set = [ing_name_by_rx[x] for x in sorted(
            {r["ingredient_rxcui"] for r in pairs if r["product_rxcui"]==prx}
        ) if x in ing_name_by_rx]
        if not ing_set:
            continue
        qas.append({
            "q": f"what are the ingredients in {pname}?",
            "intent": "product_ingredients",
            "product_name": pname,
            "answer": sorted(list(set(ing_set))),
            "split": "test"
        })
        taken += 1


    for ing_rx, pname_set in ing_products.items():
        ing_name = ing_name_by_rx.get(ing_rx)
        if not ing_name:
            continue

        names = [prod_name_by_rx[x] for x in pname_set if x in prod_name_by_rx]
        names = sorted(set(names))
        k = 10 if len(names) >= 10 else len(names)
        if k == 0:
            continue
        want = names[:k]
        qas.append({
            "q": f"list {k} products that contain {ing_name}",
            "intent": "products_by_ingredient",
            "ingredient_name": ing_name,
            "k": k,
            "answer_products": want,
            "split": "test"
        })

    
    os.makedirs(".", exist_ok=True)
    with open(OUT_QA, "w", encoding="utf-8") as f:
        for r in qas:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"[done] wrote {len(qas)} QA items to {OUT_QA}")

if __name__ == "__main__":
    main()
