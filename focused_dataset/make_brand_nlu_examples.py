import csv, os, random, yaml
random.seed(42)

IN  = "brand_generic.csv"
OUT = os.path.join("data","brand_to_generic_examples.yml")

TEMPLATES = [
  "what is the generic for {b}?",
  "generic name of {b}",
  "what's {b}'s generic?",
  "what is {b} generic called?",
  "tell me the generic for {b}",
  "find the generic for {b}"
]

def main():
    pairs = []
    with open(IN, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            b=(r.get("brand_name") or "").strip()
            g=(r.get("ingredient_name") or "").strip().lower()
            if b and g:
                pairs.append((b,g))

    seen=set(); ex=[]
    for b,g in pairs:
        k=(b.lower(), g)
        if k in seen: continue
        seen.add(k)
        for t in random.sample(TEMPLATES, k=min(3,len(TEMPLATES))):
            ex.append(f"- {t.replace('{b}', f'[{b}](brand_name)')}")

    doc={"version":"3.1","nlu":[{"intent":"brand_to_generic","examples":"\n".join(ex)}]}
    os.makedirs("data", exist_ok=True)
    with open(OUT,"w",encoding="utf-8") as f: yaml.safe_dump(doc,f,sort_keys=False,allow_unicode=True)
    print(f"[done] wrote {len(ex)} examples to {OUT}")

if __name__=="__main__":
    main()
