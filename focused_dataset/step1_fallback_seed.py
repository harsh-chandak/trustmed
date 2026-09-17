import csv, requests, os

S = requests.Session()
S.headers.update({"User-Agent":"trustmed-focus/1.0"})
NAMES = [
  "captopril","enalapril","lisinopril","perindopril","ramipril",
  "quinapril","benazepril","fosinopril","trandolapril","moexipril",
  "hydrochlorothiazide"
]

def find_rxcui(name):
    r = S.get("https://rxnav.nlm.nih.gov/REST/rxcui.json",
              params={"name": name, "search": 1}, timeout=20)
    r.raise_for_status()
    ids = (r.json().get("idGroup") or {}).get("rxnormId") or []
    return ids[0] if ids else None

rows=[]
for n in NAMES:
    rxcui = find_rxcui(n)
    if rxcui:
        rows.append({"rxcui": rxcui, "name": n, "tty": "IN",
                     "source_class": "SEED", "source_class_id": "manual"})
    else:
        print(f"[warn] could not resolve RxCUI for {n}")

os.makedirs(".", exist_ok=True)
with open("ingredients.csv","w",newline="",encoding="utf-8") as f:
    w=csv.DictWriter(f,fieldnames=["rxcui","name","tty","source_class","source_class_id"])
    w.writeheader(); w.writerows(rows)
print(f"[done] wrote {len(rows)} rows to ingredients.csv")
