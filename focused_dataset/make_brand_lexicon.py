import csv, os, re, yaml

IN = "brand_generic.csv"
OUT = os.path.join("data","brand_lexicon.yml")
ENTITY = "brand_name" 

os.makedirs("data", exist_ok=True)

brands = []
with open(IN, newline="", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        b = (r.get("brand_name") or "").strip()
        if b:
            brands.append(b)

brands = sorted(set(brands), key=lambda x: x.lower())

doc = {
  "version": "3.1",
  "nlu": [
    {
      "lookup": ENTITY,
      "examples": "\n".join(f"- {b}" for b in brands)
    }
  ]
}

with open(OUT,"w",encoding="utf-8") as f:
    yaml.safe_dump(doc, f, sort_keys=False, allow_unicode=True)

print(f"[done] wrote {len(brands)} brand entries to {OUT}")
