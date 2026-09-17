import os, sys, json, csv, re, time
import requests

BOT_URL = os.environ.get("BOT_URL", "http://localhost:5005/webhooks/rest/webhook")
SENDER  = "eval"

TRUST_RE = re.compile(r"Trust:\s*(\d+)\s*\(\s*(High|Medium|Low)\s*\)", re.I)

SALT_WORDS = {
    "maleate","hydrochloride","mesylate","fumarate","tartrate","succinate","nitrate",
    "sulfate","phosphate","acetate","citrate","potassium","sodium","medoxomil","erbumine",
    "arginine","besylate","bitartrate","hydrobromide","naphthalene","tosylate"
}


ALIASES = {
    "hydrochlorothiazide": {"hctz"},
   
}

def post_bot(msg):
    r = requests.post(BOT_URL, json={"sender": SENDER, "message": msg}, timeout=30)
    r.raise_for_status()
    return r.json()

def collect_text(resp):
    texts = []
    for item in resp:
        if "text" in item and item["text"]:
            texts.append(item["text"])
    return "\n".join(texts)

def extract_trust(text):
    m = TRUST_RE.search(text or "")
    if not m:
        return None, None
    return int(m.group(1)), m.group(2).title()

def norm(s):
    return (s or "").strip().lower()

def strip_salts(tokens):
    out = []
    for t in tokens:
        t = re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()
        parts = [p for p in t.split() if p not in SALT_WORDS]
        if parts:
            out.append(" ".join(parts))
    return out

def contains_token(text, token):
    return norm(token) in norm(text)

def friendly_match_ingredient(text, ingredient):
    t = norm(text)
    if contains_token(t, ingredient):
        return True
    
    if ingredient in ALIASES:
        for a in ALIASES[ingredient]:
            if contains_token(t, a):
                return True
            
    t_simpl = " ".join(strip_salts([t]))
    ing_simpl = " ".join(strip_salts([ingredient]))
    return contains_token(t_simpl, ing_simpl)

def STRICT_brand_to_generic(text, answer):
    return all(contains_token(text, x) for x in answer)

def FRIENDLY_brand_to_generic(text, answer):
    return all(friendly_match_ingredient(text, x) for x in answer)

def STRICT_product_ingredients(text, answer):
    return all(contains_token(text, x) for x in answer)

def FRIENDLY_product_ingredients(text, answer):
    return all(friendly_match_ingredient(text, x) for x in answer)

def STRICT_products_by_ingredient(text, expected_products, need_frac=0.6):
    if not expected_products:
        return False
    hits = sum(1 for name in expected_products if contains_token(text, name))
    need = max(1, int(round(need_frac * len(expected_products))))
    return hits >= need

def FRIENDLY_products_by_ingredient(text, expected_products, ingredient_name, need_frac=0.4):
    if expected_products:
        hits = sum(1 for name in expected_products if contains_token(text, name))
        need = max(1, int(round(need_frac * len(expected_products))))
        if hits >= need:
            return True
    
    if friendly_match_ingredient(text, ingredient_name):
        
        items = re.split(r"[;\n]|(?<=\)),\s+|,\s+", text)
        approx_items = sum(1 for it in items if len(it.strip()) > 6)
        return approx_items >= 5  
    return False

def run_eval(qas_path="qas.jsonl", out_rows="eval_results.csv"):
    qas = [json.loads(x) for x in open(qas_path, "r", encoding="utf-8").read().splitlines()]
    results = []
    agg = {
        "strict": {"total":0,"ok":0,"by_intent":{}},
        "friendly":{"total":0,"ok":0,"by_intent":{}},
    }
    for i, q in enumerate(qas, 1):
        msg = q["q"]
        try:
            resp = post_bot(msg)
            text = collect_text(resp)
        except Exception as e:
            text = f"[error contacting bot: {e}]"

        trust_score, trust_label = extract_trust(text)
        intent = q["intent"]
        
        s_ok = False
        if intent == "brand_to_generic":
            s_ok = STRICT_brand_to_generic(text, q["answer"])
        elif intent == "product_ingredients":
            s_ok = STRICT_product_ingredients(text, q["answer"])
        elif intent == "products_by_ingredient":
            s_ok = STRICT_products_by_ingredient(text, q.get("answer_products", []))
        
        f_ok = False
        if intent == "brand_to_generic":
            f_ok = FRIENDLY_brand_to_generic(text, q["answer"])
        elif intent == "product_ingredients":
            f_ok = FRIENDLY_product_ingredients(text, q["answer"])
        elif intent == "products_by_ingredient":
            f_ok = FRIENDLY_products_by_ingredient(text, q.get("answer_products", []), q.get("ingredient_name",""))

        results.append({
            "i": i, "intent": intent, "question": msg,
            "strict": int(bool(s_ok)), "friendly": int(bool(f_ok)),
            "trust_score": trust_score if trust_score is not None else "",
            "trust_label": trust_label or "",
            "text": text.replace("\n", " ")[:2000]
        })

        for mode, ok in (("strict", s_ok), ("friendly", f_ok)):
            agg[mode]["total"] += 1
            agg[mode]["ok"] += int(bool(ok))
            bi = agg[mode]["by_intent"].setdefault(intent, {"n":0,"ok":0,"trusts":[]})
            bi["n"] += 1; bi["ok"] += int(bool(ok))
            if trust_score is not None:
                bi["trusts"].append(trust_score)

        time.sleep(0.12)

    
    with open(out_rows, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "i","intent","question","strict","friendly","trust_score","trust_label","text"
        ])
        w.writeheader(); w.writerows(results)

    
    def print_summary(mode):
        a = agg[mode]; total=a["total"]; ok=a["ok"]
        acc = (ok/total) if total else 0
        print(f"{mode.upper()}")
        print(f"overall: {ok}/{total} = {acc:.2%}")
        for intent, s in a["by_intent"].items():
            iacc = (s["ok"]/s["n"]) if s["n"] else 0
            tavg = (sum(s["trusts"])/len(s["trusts"])) if s["trusts"] else None
            line = f"- {intent}: {s['ok']}/{s['n']} = {iacc:.2%}"
            if tavg is not None: line += f", avg trust ≈ {tavg:.1f}"
            print(line)

    print_summary("strict")
    print_summary("friendly")

    
    for mode in ("strict","friendly"):
        a = agg[mode]; total=a["total"]; ok=a["ok"]
        with open(f"eval_summary_{mode}.txt","w",encoding="utf-8") as f:
            acc = (ok/total) if total else 0
            f.write(f"overall: {ok}/{total} = {acc:.2%}\n")
            for intent, s in a["by_intent"].items():
                iacc = (s["ok"]/s["n"]) if s["n"] else 0
                tavg = (sum(s["trusts"])/len(s["trusts"])) if s["trusts"] else None
                f.write(f"{intent}: {s['ok']}/{s['n']} = {iacc:.2%}"
                        + (f", avg trust ≈ {tavg:.1f}" if tavg is not None else "")
                        + "\n")

if __name__ == "__main__":
    qpath = sys.argv[1] if len(sys.argv)>1 else "qas.jsonl"
    out   = sys.argv[2] if len(sys.argv)>2 else "eval_results.csv"
    run_eval(qpath, out)
