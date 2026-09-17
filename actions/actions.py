from __future__ import annotations

import os, csv, re
from typing import List, Dict, Any, Optional, Tuple

from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet, EventType

from collections import defaultdict

from .knowledge_base import get_kb, KnowledgeBase

def _ok(payload: Any) -> Dict[str, Any]:
    return {"ok": True, "data": payload}

def _err(msg: str, detail: Optional[str] = None) -> Dict[str, Any]:
    out = {"ok": False, "error": msg}
    if detail:
        out["detail"] = detail
    return out

def _fmt_list(items: List[str], empty_msg: str) -> str:
    if not items:
        return empty_msg
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + f", and {items[-1]}"

def _limit(items: List[Any], n: int) -> List[Any]:
    return items[:n] if n and n > 0 else items

def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())

def _extract_brand_key(text: str) -> Optional[str]:
    
    bmap, _ = _load_focus_overlay()
    if not bmap:
        return None
    t = _normalize(text)
    best = None
    for b in bmap.keys():
        if b in t:
            if best is None or len(b) > len(best):
                best = b
    return best

def _best_product_name_key(text: str) -> Optional[str]:
    
    g = _load_focus_graph()
    if not g:
        return None
    names = list(g.get("prod_to_rx", {}).keys())  
    t = _normalize(text)

    
    if t in names:
        return t

    
    cand = [n for n in names if t in n or n in t]
    if cand:
        return max(cand, key=len)

    return None

_TRUST_PRIOR = {
    "product_ingredients": 0.95,         
    "products_by_ingredient": 0.85,       
    "product_substitutes": 0.90,          
    "co_ingredient_partners": 0.70,       
    "similar_by_combo_overlap": 0.65,     
    "brand_to_generic": 0.95,             
    "generic_to_brands": 0.90,            
    "extract_strengths": 0.70,            
    "get_ancestry_paths": 0.60,          
}

_REASON_TAG = {
    "product_ingredients": "direct product→ingredient link",
    "products_by_ingredient": "ingredient→products links",
    "product_substitutes": "same active set comparison",
    "co_ingredient_partners": "co-occurrence across products",
    "similar_by_combo_overlap": "overlap of co-formulation partners",
    "brand_to_generic": "direct brand↔generic link",
    "generic_to_brands": "direct generic↔brand link",
    "extract_strengths": "regex parsing near product names",
    "get_ancestry_paths": "ontology path traversal",
}

def _trust_label(score: int) -> str:
    if score >= 80:
        return "High"
    if score >= 60:
        return "Medium"
    return "Low"

def _compute_trust(method: str, result_count: int, tracker, slots_present: bool) -> dict:
    
    
    data = _TRUST_PRIOR.get(method, 0.75)

    
    if method in ("brand_to_generic", "product_ingredients"):
        q = 1.0 if result_count > 0 else 0.7
    elif method in ("products_by_ingredient", "product_substitutes", "generic_to_brands"):
        q = 0.9 if result_count > 0 else 0.6
    elif method in ("co_ingredient_partners", "similar_by_combo_overlap", "extract_strengths"):
        q = 0.7 if result_count > 0 else 0.5
    else:
        q = 0.8 if result_count > 0 else 0.6

    
    try:
        nlu = float(tracker.latest_message.get("intent", {}).get("confidence", 0.0))
    except Exception:
        nlu = 0.0
    nlu = max(0.0, min(1.0, nlu))
    if not slots_present:
        nlu = min(nlu, 0.6)  

    
    score01 = 0.5 * data + 0.3 * q + 0.2 * nlu
    score = int(round(100 * score01))
    label = _trust_label(score)

    
    reason_parts = [_REASON_TAG.get(method, "graph lookup")]
    if result_count > 0:
        reason_parts.append("short path with results")
    if nlu >= 0.9:
        reason_parts.append("high NLU confidence")
    elif nlu < 0.6:
        reason_parts.append("low NLU confidence")
    if not slots_present:
        reason_parts.append("entity uncertain")

    return {"score": score, "label": label, "reason": "; ".join(reason_parts)}

FOCUS_DIR = os.getenv("FOCUS_DIR", "/app/focused_dataset")
BRAND_GENERIC_CSV = os.path.join(FOCUS_DIR, "brand_generic.csv")
EVIDENCE_CSV      = os.path.join(FOCUS_DIR, "evidence.csv")

_focus_brand_map = None
_focus_evidence  = None

def _load_focus_overlay():
    
    global _focus_brand_map, _focus_evidence
    if _focus_brand_map is not None:
        return _focus_brand_map, _focus_evidence

    brand_map = defaultdict(set)
    evidence  = defaultdict(list)

    try:
        with open(BRAND_GENERIC_CSV, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                b = (r.get("brand_name") or "").strip().lower()
                g = (r.get("ingredient_name") or "").strip().lower()
                if b and g:
                    brand_map[b].add(g)
    except FileNotFoundError:
        pass

    try:
        with open(EVIDENCE_CSV, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if (r.get("entity_type") or "").lower() == "brand":
                    b = (r.get("key_text") or "").strip().lower()
                    p = (r.get("pointer") or "").strip()
                    if b and p:
                        evidence[b].append(p)
    except FileNotFoundError:
        pass

    _focus_brand_map = brand_map
    _focus_evidence  = evidence
    return brand_map, evidence

PRODUCTS_CSV = os.path.join(FOCUS_DIR, "products.csv")
PAIRS_CSV    = os.path.join(FOCUS_DIR, "product_ingredient.csv")
ING_CSV      = os.path.join(FOCUS_DIR, "ingredients.csv")

_focus_graph = None

def _load_focus_graph():
    global _focus_graph
    if _focus_graph is not None:
        return _focus_graph

    if not (os.path.exists(PRODUCTS_CSV) and os.path.exists(PAIRS_CSV) and os.path.exists(ING_CSV)):
        _focus_graph = {}
        return _focus_graph

    rx_to_prod = {}
    prod_to_rx = {}
    rx_to_ing  = {}
    ing_to_rx  = {}

    with open(PRODUCTS_CSV, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            prx = (r.get("product_rxcui") or "").strip()
            pname = (r.get("product_name") or "").strip()
            if prx and pname:
                rx_to_prod[prx] = pname
                prod_to_rx[pname.lower()] = prx

    with open(ING_CSV, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            irx = (r.get("rxcui") or "").strip()
            iname = (r.get("name") or "").strip()
            tty = (r.get("tty") or "").strip()
            if irx and iname and tty.upper() == "IN":
                rx_to_ing[irx] = iname
                ing_to_rx[iname.lower()] = irx

    prod_to_ings = {}
    ing_to_prods = {}
    with open(PAIRS_CSV, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            prx = (r.get("product_rxcui") or "").strip()
            irx = (r.get("ingredient_rxcui") or "").strip()
            if not prx or not irx:
                continue
            prod_to_ings.setdefault(prx, set()).add(irx)
            ing_to_prods.setdefault(irx, set()).add(prx)

    _focus_graph = {
        "rx_to_prod": rx_to_prod, "prod_to_rx": prod_to_rx,
        "rx_to_ing": rx_to_ing,   "ing_to_rx": ing_to_rx,
        "prod_to_ings": prod_to_ings, "ing_to_prods": ing_to_prods,
    }
    return _focus_graph


def _overlay_product_ingredients(product_name: str) -> List[str]:
    
    g = _load_focus_graph()
    if not g:
        return []
    prx = g["prod_to_rx"].get(product_name.lower())
    if not prx:
        return []
    irxs = g["prod_to_ings"].get(prx, set())
    names = [g["rx_to_ing"].get(irx) for irx in irxs]
    return sorted({n for n in names if n})


def _overlay_products_by_ingredient(ingredient_name: str, limit: int = 50) -> List[str]:
   
    g = _load_focus_graph()
    if not g:
        return []
    irx = g["ing_to_rx"].get(ingredient_name.lower())
    if not irx:
        return []
    prxs = list(g["ing_to_prods"].get(irx, set()))
    names = [g["rx_to_prod"].get(prx) for prx in prxs]
    names = [n for n in names if n]
    names = sorted(set(names))
    return names[: max(1, int(limit))]

def _overlay_product_ingredients(product_name: str) -> List[str]:
    
    g = _load_focus_graph()
    if not g:
        return []
    prx = g["prod_to_rx"].get(product_name.lower())
    if not prx:
        return []
    irxs = g["prod_to_ings"].get(prx, set())
    names = [g["rx_to_ing"].get(irx) for irx in irxs]
    return sorted({n for n in names if n})


def _overlay_products_by_ingredient(ingredient_name: str, limit: int = 50) -> List[str]:
    
    g = _load_focus_graph()
    if not g:
        return []
    irx = g["ing_to_rx"].get(ingredient_name.lower())
    if not irx:
        return []
    prxs = list(g["ing_to_prods"].get(irx, set()))
    names = [g["rx_to_prod"].get(prx) for prx in prxs]
    names = [n for n in names if n]
    names = sorted(set(names))
    return names[: max(1, int(limit))]

def _overlay_substitutes_same_actives(product_name: str, limit: int = 50) -> List[str]:
    g = _load_focus_graph()
    if not g:
        return []
    
    key = _best_product_name_key(product_name) or _normalize(product_name)
    prx = g["prod_to_rx"].get(key)
    if not prx:
        return []
    actives = g["prod_to_ings"].get(prx, set())
    if not actives:
        return []
    subs = []
    for prx2, ings2 in g["prod_to_ings"].items():
        if prx2 == prx:
            continue
        if ings2 == actives:  
            name = g["rx_to_prod"].get(prx2)
            if name:
                subs.append(name)
    subs = sorted(set(subs))
    return subs[:max(1, int(limit))]

class Actions:

    def __init__(self, kb: Optional[KnowledgeBase] = None):
        self.kb = kb or get_kb()

    
    def get_product_ingredients(self, product_name: str) -> Dict[str, Any]:
        try:
            if not product_name:
                return _err("Missing product_name.")
            ingredients = self.kb.product_ingredients(product_name)
            text = (
                f"Active ingredient(s) in {product_name}: "
                f"{_fmt_list(ingredients, 'no active ingredients found')}"
            )
            return {**_ok({"product": product_name, "ingredients": ingredients}), "text": text}
        except Exception as e:
            return _err("Failed to fetch product ingredients.", str(e))

    
    def get_products_by_ingredient(self, ingredient_name: str, limit: int = 50) -> Dict[str, Any]:
        try:
            if not ingredient_name:
                return _err("Missing ingredient_name.")
            products = self.kb.products_by_ingredient(ingredient_name, limit=limit)
            text = (
                f"Products containing {ingredient_name}: "
                f"{_fmt_list(_limit(products, 10), 'none found')}"
            )
            return {**_ok({"ingredient": ingredient_name, "products": products}), "text": text}
        except Exception as e:
            return _err("Failed to fetch products by ingredient.", str(e))

    
    def get_product_substitutes(self, product_name: str, limit: int = 50) -> Dict[str, Any]:
        try:
            if not product_name:
                return _err("Missing product_name.")
            subs = self.kb.product_substitutes_same_actives(product_name, limit=limit)
            text = (
                f"Products with the same active ingredients as {product_name}: "
                f"{_fmt_list(_limit(subs, 10), 'none found')}"
            )
            return {**_ok({"product": product_name, "substitutes": subs}), "text": text}
        except Exception as e:
            return _err("Failed to fetch product substitutes.", str(e))

    
    def get_co_ingredient_partners(self, ingredient_name: str, limit: int = 100) -> Dict[str, Any]:
        try:
            if not ingredient_name:
                return _err("Missing ingredient_name.")
            partners = self.kb.co_ingredient_partners(ingredient_name, limit=limit)
            text = (
                f"Common co-ingredients with {ingredient_name}: "
                f"{_fmt_list(_limit(partners, 15), 'none found')}"
            )
            return {**_ok({"ingredient": ingredient_name, "partners": partners}), "text": text}
        except Exception as e:
            return _err("Failed to fetch co-ingredient partners.", str(e))

    
    def get_similar_by_combo_overlap(self, ingredient_name: str, limit: int = 50) -> Dict[str, Any]:
        try:
            if not ingredient_name:
                return _err("Missing ingredient_name.")
            rows = self.kb.similar_by_combo_overlap(ingredient_name, limit=limit)
            
            top_preview = [f"{r['name']} (score {r['overlap']})" for r in _limit(rows, 10)]
            text = (
                f"Ingredients related to {ingredient_name} by frequent co-formulation: "
                f"{_fmt_list(top_preview, 'none found')}"
            )
            return {**_ok({"seed": ingredient_name, "similar": rows}), "text": text}
        except Exception as e:
            return _err("Failed to compute combo-overlap similarity.", str(e))

    
    def brand_to_generic(self, brand_name: str) -> Dict[str, Any]:
        try:
            if not brand_name:
                return _err("Missing brand_name.")
            generics = self.kb.brand_to_generic(brand_name)
            text = (
                f"Generic for {brand_name}: {_fmt_list(generics, 'none found')}"
            )
            return {**_ok({"brand": brand_name, "generics": generics}), "text": text}
        except Exception as e:
            return _err("Failed to fetch generic names.", str(e))

    
    def generic_to_brands(self, generic_name: str) -> Dict[str, Any]:
        try:
            if not generic_name:
                return _err("Missing generic_name.")
            brands = self.kb.generic_to_brands(generic_name)
            text = (
                f"Brands for {generic_name}: {_fmt_list(_limit(brands, 15), 'none found')}"
            )
            return {**_ok({"generic": generic_name, "brands": brands}), "text": text}
        except Exception as e:
            return _err("Failed to fetch brands.", str(e))

    
    def extract_strengths(self, ingredient_name: str, limit: int = 100) -> Dict[str, Any]:
        try:
            if not ingredient_name:
                return _err("Missing ingredient_name.")
            rows = self.kb.extract_strengths_from_products(ingredient_name, limit=limit)
            
            preview = [f"{r['product']} → {', '.join(r['strengths'])}" for r in _limit(rows, 5)]
            text = (
                f"Extracted strengths near {ingredient_name}: "
                f"{_fmt_list(preview, 'none found')}"
            )
            return {**_ok({"ingredient": ingredient_name, "strengths": rows}), "text": text}
        except Exception as e:
            return _err("Failed to extract strengths (APOC needed?).", str(e))

    
    def get_ancestry_paths(self, drug_name: str, max_depth: int = 4) -> Dict[str, Any]:
        try:
            if not drug_name:
                return _err("Missing drug_name.")
            paths = self.kb.ancestry_path(drug_name, max_depth=max_depth)
            
            preview = [" → ".join(p) for p in _limit(paths, 5)]
            text = (
                f"Ontology paths from {drug_name}: "
                f"{_fmt_list(preview, 'none found')}"
            )
            return {**_ok({"drug": drug_name, "paths": paths}), "text": text}
        except Exception as e:
            return _err("Failed to compute ancestry paths.", str(e))



_FACADE = Actions()

def _get_slot(tracker: Tracker, name: str, default: str = "") -> str:
    val = tracker.get_slot(name)
    if isinstance(val, str):
        return val.strip()
    return default

def _get_slot_or_entity(tracker: Tracker, slot_name: str, entity_name: Optional[str] = None, default: str = "") -> str:
    
    val = _get_slot(tracker, slot_name, default)
    if val:
        return val
    entity_name = entity_name or slot_name
    try:
        for e in tracker.latest_message.get("entities", []) or []:
            if (e.get("entity") or "").strip().lower() == entity_name and e.get("value"):
                return str(e["value"]).strip()
    except Exception:
        pass
    return default

class ActionGetProductIngredients(Action):
    def name(self) -> str:
        return "action_get_product_ingredients"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: dict) -> list[EventType]:
        
        product_name = _get_slot_or_entity(tracker, "product_name", "product_name")
        user_text    = tracker.latest_message.get("text", "")

        
        key = _best_product_name_key(product_name or user_text)
        display_name = product_name or (key or "").title()

        
        if key:
            
            ov = _overlay_product_ingredients(key)  
            if ov:
                msg = f"Active ingredient(s) in {display_name}: {_fmt_list(ov, 'none found')}"
                trust = _compute_trust("product_ingredients", len(ov), tracker, slots_present=True)
                trust["score"] = min(100, trust["score"] + 5)  
                trust["label"] = _trust_label(trust["score"])
                dispatcher.utter_message(text=msg)
                dispatcher.utter_message(
                    text=f"Trust: {trust['score']} ({trust['label']}). "
                         f"Why: focused dataset match; {_REASON_TAG['product_ingredients']}; high NLU confidence."
                )
                return []

        
        use_name = product_name or user_text
        res = _FACADE.get_product_ingredients(use_name)
        count = len(res.get("data", {}).get("ingredients", [])) if res.get("ok") else 0
        trust = _compute_trust("product_ingredients", count, tracker, slots_present=bool(use_name))
        msg = (res.get("text") or "No results.")
        msg += f"\n\nTrust: {trust['score']} ({trust['label']}). Why: {trust['reason']}."
        dispatcher.utter_message(text=msg)
        return []

class ActionGetProductsByIngredient(Action):
    def name(self) -> str:
        return "action_get_products_by_ingredient"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: dict) -> list[EventType]:
        ingredient_name = _get_slot_or_entity(tracker, "ingredient_name", "ingredient_name")
        if not ingredient_name:
            dispatcher.utter_message(text="Sorry — I couldn't detect the ingredient name.")
            return []

        top_k = tracker.get_slot("top_k")
        try:
            limit = int(top_k) if top_k is not None else 50
        except Exception:
            limit = 50

        
        ov = _overlay_products_by_ingredient(ingredient_name, limit=limit)
        if ov:
            msg = f"Products containing {ingredient_name}: {_fmt_list(_limit(ov, 10), 'none found')}"
            trust = _compute_trust("products_by_ingredient", len(ov), tracker, slots_present=True)
            trust["score"] = min(100, trust["score"] + 5)
            trust["label"] = _trust_label(trust["score"])
            dispatcher.utter_message(text=msg)
            dispatcher.utter_message(text=f"Trust: {trust['score']} ({trust['label']}). Why: focused dataset match; {_REASON_TAG['products_by_ingredient']}.")
            return []

        
        res = _FACADE.get_products_by_ingredient(ingredient_name, limit=limit)
        count = len(res.get("data", {}).get("products", [])) if res.get("ok") else 0
        trust = _compute_trust("products_by_ingredient", count, tracker, slots_present=bool(ingredient_name))
        msg = (res.get("text") or "No results.")
        msg += f"\n\nTrust: {trust['score']} ({trust['label']}). Why: {trust['reason']}."
        dispatcher.utter_message(text=msg)
        return []

def run(self, dispatcher, tracker, domain):
    product_name = _get_slot_or_entity(tracker, "product_name", "product_name")
    top_k = tracker.get_slot("top_k")
    try: limit = int(top_k) if top_k is not None else 25
    except: limit = 25

    
    ov = _overlay_substitutes_same_actives(product_name, limit=limit) if product_name else []
    if ov:
        msg = f"Products with the same active ingredients as {product_name}: {_fmt_list(_limit(ov, 10), 'none found')}"
        trust = _compute_trust("product_substitutes", len(ov), tracker, slots_present=bool(product_name))
        trust["score"] = min(100, trust["score"] + 5)
        trust["label"] = _trust_label(trust["score"])
        dispatcher.utter_message(text=msg)
        dispatcher.utter_message(text=f"Trust: {trust['score']} ({trust['label']}). Why: focused dataset match; same active set comparison.")
        return []

    
    res = _FACADE.get_product_substitutes(product_name, limit=limit)
    data = res.get("data", {}) if res.get("ok") else {}
    list_key = "substitutes" if "substitutes" in data else "products"
    count = len(data.get(list_key, [])) if data else 0
    trust = _compute_trust("product_substitutes", count, tracker, slots_present=bool(product_name))
    msg = (res.get("text") or "No substitutes found.")
    msg += f"\n\nTrust: {trust['score']} ({trust['label']}). Why: {trust['reason']}."
    dispatcher.utter_message(text=msg)
    return []

class ActionGetCoIngredientPartners(Action):
    def name(self) -> str:
        return "action_get_co_ingredient_partners"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: dict) -> list[EventType]:
        ingredient_name = _get_slot(tracker, "ingredient_name")
        top_k = tracker.get_slot("top_k")
        try:
            limit = int(top_k) if top_k is not None else 25
        except Exception:
            limit = 25

        res = _FACADE.get_co_ingredient_partners(ingredient_name, limit=limit)

        
        data = res.get("data", {}) if res.get("ok") else {}
        list_key = "partners" if "partners" in data else "ingredients"
        count = len(data.get(list_key, [])) if data else 0

        trust = _compute_trust("co_ingredient_partners", count, tracker, slots_present=bool(ingredient_name))

        msg = (res.get("text") or "No co-ingredients found.")
        msg += f"\n\nTrust: {trust['score']} ({trust['label']}). Why: {trust['reason']}."
        dispatcher.utter_message(text=msg)
        return []

class ActionGetSimilarByComboOverlap(Action):
    def name(self) -> str:
        return "action_get_similar_by_combo_overlap"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: dict) -> list[EventType]:
        ingredient_name = _get_slot(tracker, "ingredient_name")
        top_k = tracker.get_slot("top_k")
        try:
            limit = int(top_k) if top_k is not None else 25
        except Exception:
            limit = 25

        res = _FACADE.get_similar_by_combo_overlap(ingredient_name, limit=limit)

        count = len(res.get("data", {}).get("similar", [])) if res.get("ok") else 0
        trust = _compute_trust("similar_by_combo_overlap", count, tracker, slots_present=bool(ingredient_name))

        msg = (res.get("text") or "No similar ingredients found.")
        msg += f"\n\nTrust: {trust['score']} ({trust['label']}). Why: {trust['reason']}."
        dispatcher.utter_message(text=msg)
        return []

class ActionBrandToGeneric(Action):
    def name(self) -> str:
        return "action_brand_to_generic"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: dict) -> list[EventType]:
        
        brand_name = _get_slot_or_entity(tracker, "brand_name", "brand_name")
        user_text  = tracker.latest_message.get("text", "")

        
        brand_key = None
        if not brand_name or len(brand_name.split()) > 3:
            
            m = re.search(r"generic\s+for\s+(.+?)\s*\?*$", user_text, flags=re.I)
            cand = m.group(1).strip() if m else brand_name
            brand_key = _extract_brand_key(cand or user_text)
        else:
            brand_key = _extract_brand_key(brand_name) or _normalize(brand_name)

        nlu_conf = float(tracker.latest_message.get("intent", {}).get("confidence", 0.0) or 0.0)

        
        bmap, evid = _load_focus_overlay()
        hits = sorted(bmap.get(brand_key or "", []))

        if hits:
            display_brand = brand_name or (brand_key or "").title()
            msg = f"The generic for {display_brand} is {_fmt_list(hits, 'none found')}."
            dispatcher.utter_message(text=msg)

            trust = _compute_trust("brand_to_generic", len(hits), tracker, slots_present=True)
            trust["score"] = min(100, trust["score"] + 5)  
            trust["label"] = _trust_label(trust["score"])
            dispatcher.utter_message(
                text=f"Trust: {trust['score']} ({trust['label']}). "
                     f"Why: exact match in focused brand↔generic mapping; NLU {int(nlu_conf*100)}%."
            )

            ev = evid.get(brand_key or "", [])
            if ev:
                dispatcher.utter_message(text=f"Evidence: openFDA label id(s) {', '.join(ev[:2])}.")
            return []

        
        use_name = brand_name or (brand_key or "")
        if not use_name:
            dispatcher.utter_message(text="Sorry — I couldn't detect the brand name.")
            return []

        res = _FACADE.brand_to_generic(use_name)
        count = len(res.get("data", {}).get("generics", [])) if res.get("ok") else 0
        trust = _compute_trust("brand_to_generic", count, tracker, slots_present=bool(use_name))
        msg = (res.get("text") or "No generic found.")
        msg += f"\n\nTrust: {trust['score']} ({trust['label']}). Why: {trust['reason']}."
        dispatcher.utter_message(text=msg)
        return []

class ActionGenericToBrands(Action):
    def name(self) -> str:
        return "action_generic_to_brands"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: dict) -> list[EventType]:
        generic_name = _get_slot(tracker, "generic_name")
        top_k = tracker.get_slot("top_k")
        try:
            limit = int(top_k) if top_k is not None else 50
        except Exception:
            limit = 50

        res = _FACADE.generic_to_brands(generic_name, limit=limit)

        count = len(res.get("data", {}).get("brands", [])) if res.get("ok") else 0
        trust = _compute_trust("generic_to_brands", count, tracker, slots_present=bool(generic_name))

        msg = (res.get("text") or "No brands found.")
        msg += f"\n\nTrust: {trust['score']} ({trust['label']}). Why: {trust['reason']}."
        dispatcher.utter_message(text=msg)
        return []

class ActionExtractStrengths(Action):
    def name(self) -> str:
        return "action_extract_strengths"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: dict) -> list[EventType]:
        drug_name = _get_slot(tracker, "ingredient_name") or _get_slot(tracker, "product_name") or _get_slot(tracker, "generic_name")
        top_k = tracker.get_slot("top_k")
        try:
            limit = int(top_k) if top_k is not None else 25
        except Exception:
            limit = 25

        res = _FACADE.extract_strengths(drug_name, limit=limit)

        count = len(res.get("data", {}).get("strengths", [])) if res.get("ok") else 0
        trust = _compute_trust("extract_strengths", count, tracker, slots_present=bool(drug_name))

        msg = (res.get("text") or "No strengths parsed.")
        msg += f"\n\nTrust: {trust['score']} ({trust['label']}). Why: {trust['reason']}."
        dispatcher.utter_message(text=msg)
        return []

class ActionGetAncestryPaths(Action):
    def name(self) -> str:
        return "action_get_ancestry_paths"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: dict) -> list[EventType]:
        drug_name = _get_slot(tracker, "ingredient_name") or _get_slot(tracker, "generic_name") or _get_slot(tracker, "product_name")
        
        depth = tracker.get_slot("max_depth")
        try:
            max_depth = int(depth) if depth is not None else 3
        except Exception:
            max_depth = 3

        res = _FACADE.get_ancestry_paths(drug_name, max_depth=max_depth)

        count = len(res.get("data", {}).get("paths", [])) if res.get("ok") else 0
        trust = _compute_trust("get_ancestry_paths", count, tracker, slots_present=bool(drug_name))

        msg = (res.get("text") or "No paths found.")
        msg += f"\n\nTrust: {trust['score']} ({trust['label']}). Why: {trust['reason']}."
        dispatcher.utter_message(text=msg)
        return []


if __name__ == "__main__":
    
    a = Actions()

    seed = os.getenv("SEED_INGREDIENT", "ibuprofen")
    sample_product = os.getenv("SAMPLE_PRODUCT", "HCTZ 12.5 MG / lisinopril 20 MG Oral Tablet")
    sample_brand = os.getenv("SAMPLE_BRAND", "Zestril")
    sample_generic = os.getenv("SAMPLE_GENERIC", "lisinopril")

    print("\nProduct to Ingredients ")
    print(a.get_product_ingredients(sample_product))

    print("\nIngredient to Products")
    print(a.get_products_by_ingredient(seed, limit=20))

    print("\nProduct substitutes")
    print(a.get_product_substitutes(sample_product, limit=20))

    print("\nCo-ingredient partners")
    print(a.get_co_ingredient_partners(seed, limit=30))

    print("\nSimilar by combo overlap")
    print(a.get_similar_by_combo_overlap(seed, limit=30))

    print("\nBrand to Generic")
    print(a.brand_to_generic(sample_brand))

    print("\nGeneric to Brands")
    print(a.generic_to_brands(sample_generic))

    print("\nStrength extraction")
    print(a.extract_strengths(seed, limit=20))

    print("\nAncestry paths")
    print(a.get_ancestry_paths(seed, max_depth=4))
