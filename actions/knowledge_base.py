from __future__ import annotations

import os
from typing import List, Dict, Any, Optional
from neo4j import GraphDatabase, Driver


class KnowledgeBase:
    def __init__(
        self,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        database: Optional[str] = None,
    ):
        self.uri = uri or os.getenv("NEO4J_URI", "bolt://trustmed-db:7687")
        self.user = user or os.getenv("NEO4J_USER", "neo4j")
        self.password = password or os.getenv("NEO4J_PASSWORD", "password123")
        self.database = database or os.getenv("NEO4J_DATABASE", "neo4j")

        self.driver: Optional[Driver] = None
        try:
            self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
            
            self.driver.verify_connectivity()
            print(f"[KnowledgeBase] Connected to {self.uri} (db='{self.database}') as {self.user}.")
        except Exception as e:
            print(f"[KnowledgeBase] Connection failed: {e}")
            self.driver = None

    def close(self) -> None:
        if self.driver is not None:
            self.driver.close()
            self.driver = None

    def _run_query(self, query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        if self.driver is None:
            return []
        with self.driver.session(database=self.database) as session:
            result = session.run(query, params or {})
            return [r.data() for r in result]

    def product_ingredients(self, product_name: str) -> List[str]:
        
        if not product_name:
            return []
        q = """
        WITH toLower($product_name) AS plc
        CALL {
          WITH plc
          MATCH (p:Concept {name_lc: plc})-[r:RELATED_TO]->(i:Concept)
          WHERE r.type='has_active_ingredient'
          RETURN i.name AS ingredient
          UNION
          WITH plc
          MATCH (i:Concept)-[r:RELATED_TO]->(p:Concept {name_lc: plc})
          WHERE r.type='has_active_ingredient'
          RETURN i.name AS ingredient
        }
        RETURN DISTINCT ingredient ORDER BY ingredient
        """
        rows = self._run_query(q, {"product_name": product_name})
        return [r["ingredient"] for r in rows]

    def products_by_ingredient(self, ingredient_name: str, limit: int = 50) -> List[str]:
       
        if not ingredient_name:
            return []
        q = """
        WITH toLower($ingredient_name) AS ilc
        CALL {
          WITH ilc
          MATCH (i:Concept {name_lc: ilc})-[r:RELATED_TO]->(p:Concept)
          WHERE r.type IN ['has_ingredient','has_active_ingredient'] OR r.rela='RO'
          RETURN p.name AS product
          UNION
          WITH ilc
          MATCH (p:Concept)-[r:RELATED_TO]->(i:Concept {name_lc: ilc})
          WHERE r.type IN ['has_ingredient','has_active_ingredient'] OR r.rela='RO'
          RETURN p.name AS product
        }
        RETURN DISTINCT product ORDER BY product LIMIT $limit
        """
        rows = self._run_query(q, {"ingredient_name": ingredient_name, "limit": limit})
        return [r["product"] for r in rows]

    def product_substitutes_same_actives(self, product_name: str, limit: int = 50) -> List[str]:
      
        if not product_name:
            return []
        q = """
        WITH toLower($product_name) AS plc
        MATCH (p:Concept {name_lc: plc})
        CALL {
          WITH p
          MATCH (p)-[r:RELATED_TO]->(ai:Concept) WHERE r.type='has_active_ingredient'
          RETURN DISTINCT ai
          UNION
          WITH p
          MATCH (ai:Concept)-[r:RELATED_TO]->(p) WHERE r.type='has_active_ingredient'
          RETURN DISTINCT ai
        }
        WITH p, collect(DISTINCT ai) AS actives
        MATCH (p2:Concept) WHERE p2 <> p
        AND ALL(a IN actives WHERE
          EXISTS { MATCH (p2)-[r2:RELATED_TO]->(a) WHERE r2.type='has_active_ingredient' } OR
          EXISTS { MATCH (a)-[r3:RELATED_TO]->(p2) WHERE r3.type='has_active_ingredient' })
        RETURN DISTINCT p2.name AS substitute
        ORDER BY substitute LIMIT $limit
        """
        rows = self._run_query(q, {"product_name": product_name, "limit": limit})
        return [r["substitute"] for r in rows]

    def co_ingredient_partners(self, ingredient_name: str, limit: int = 100) -> List[str]:
       
        if not ingredient_name:
            return []
        q = """
        WITH toLower($drug_name) AS dlc
        MATCH (i:Concept {name_lc: dlc})-[:RELATED_TO {type:'has_active_ingredient'}]->(prod:Concept)
        CALL {
          WITH dlc, prod
          MATCH (prod)-[r1:RELATED_TO]->(o:Concept)
          WHERE r1.type IN ['has_active_ingredient','has_ingredient','has_boss'] AND o.name_lc <> dlc
          RETURN o AS other
          UNION
          WITH dlc, prod
          MATCH (o:Concept)-[r2:RELATED_TO]->(prod)
          WHERE r2.type IN ['has_active_ingredient','has_ingredient','has_boss'] AND o.name_lc <> dlc
          RETURN o AS other
        }
        WITH dlc, other
        WHERE NOT EXISTS { MATCH (other)-[:RELATED_TO {type:'has_tradename'}]->(:Concept) }
          AND NOT EXISTS { MATCH (:Concept)-[:RELATED_TO {type:'tradename_of'}]->(other) }
          AND NOT EXISTS { MATCH (other)-[:RELATED_TO {type:'has_dose_form'}]->(:Concept) }
          AND NOT other.name_lc CONTAINS ' / '
          AND NOT other.name_lc =~ '.*\\b(oral|topical|tablet|capsule|injection|suspension|gel|cream|spray|suppository|ophthalmic|lozenge|rectal|mg|ml|%)\\b.*'
        RETURN DISTINCT other.name AS name
        ORDER BY toLower(name) LIMIT $limit
        """
        rows = self._run_query(q, {"drug_name": ingredient_name, "limit": limit})
        return [r["name"] for r in rows]

    def similar_by_combo_overlap(self, ingredient_name: str, limit: int = 50) -> List[Dict[str, Any]]:
        if not ingredient_name:
            return []
        q = """
        WITH toLower($drug_name) AS dlc
        MATCH (i:Concept {name_lc: dlc})-[:RELATED_TO {type:'has_active_ingredient'}]->(prod:Concept)
        WITH dlc, collect(DISTINCT prod) AS prods
        UNWIND prods AS prod
        MATCH (partner:Concept)-[:RELATED_TO {type:'has_active_ingredient'}]->(prod)
        WHERE partner.name_lc <> dlc
          AND NOT EXISTS { MATCH (partner)-[:RELATED_TO {type:'has_tradename'}]->(:Concept) }
          AND NOT EXISTS { MATCH (:Concept)-[:RELATED_TO {type:'tradename_of'}]->(partner) }
          AND NOT EXISTS { MATCH (partner)-[:RELATED_TO {type:'has_dose_form'}]->(:Concept) }
          AND NOT partner.name_lc CONTAINS ' / '
          AND NOT partner.name_lc =~ '.*\\b(oral|topical|tablet|capsule|injection|suspension|gel|cream|spray|suppository|ophthalmic|lozenge|rectal|mg|ml|%)\\b.*'
        WITH dlc, collect(DISTINCT partner) AS partners
        UNWIND partners AS partner
        MATCH (cand:Concept)-[:RELATED_TO {type:'has_active_ingredient'}]->(:Concept)
              <-[:RELATED_TO {type:'has_active_ingredient'}]-(partner)
        WHERE cand.name_lc <> dlc
          AND NOT EXISTS { MATCH (cand)-[:RELATED_TO {type:'has_tradename'}]->(:Concept) }
          AND NOT EXISTS { MATCH (:Concept)-[:RELATED_TO {type:'tradename_of'}]->(cand) }
          AND NOT EXISTS { MATCH (cand)-[:RELATED_TO {type:'has_dose_form'}]->(:Concept) }
          AND NOT cand.name_lc CONTAINS ' / '
          AND NOT cand.name_lc =~ '.*\\b(oral|topical|tablet|capsule|injection|suspension|gel|cream|spray|suppository|ophthalmic|lozenge|rectal|mg|ml|%)\\b.*'
        RETURN cand.name AS name, count(*) AS partner_overlap
        ORDER BY partner_overlap DESC, toLower(name)
        LIMIT $limit
        """
        rows = self._run_query(q, {"drug_name": ingredient_name, "limit": limit})
        return [{"name": r["name"], "overlap": r["partner_overlap"]} for r in rows]

    def brand_to_generic(self, brand_name: str) -> List[str]:
        if not brand_name:
            return []
        q = """
        WITH toLower($brand_name) AS blc
        MATCH (b:Concept) WHERE b.name_lc = blc
        MATCH (b)-[:RELATED_TO {type:'has_tradename'}]->(g:Concept)
        RETURN DISTINCT g.name AS name
        """
        rows = self._run_query(q, {"brand_name": brand_name})
        return [r["name"] for r in rows]

    def generic_to_brands(self, generic_name: str) -> List[str]:
        if not generic_name:
            return []
        q = """
        WITH toLower($generic_name) AS glc
        MATCH (b:Concept)-[:RELATED_TO {type:'has_tradename'}]->(g:Concept)
        WHERE g.name_lc = glc
        RETURN DISTINCT b.name AS name ORDER BY name
        """
        rows = self._run_query(q, {"generic_name": generic_name})
        return [r["name"] for r in rows]

    def extract_strengths_from_products(self, drug_name: str, limit: int = 100) -> List[Dict[str, Any]]:
        if not drug_name:
            return []
        q = """
        WITH toLower($drug_name) AS dlc
        MATCH (d:Concept) WHERE d.name_lc = dlc
        MATCH (d)-[r:RELATED_TO]->(p:Concept)
        WHERE (r.type IN ['has_active_ingredient','has_boss'] OR r.rela='RO')
        WITH DISTINCT p.name AS n
        WITH n,
          apoc.text.regexGroups(n, '(\\d+(?:\\.\\d+)?)\\s*(mg|mcg|g|ml|%)') AS simple,
          apoc.text.regexGroups(n, '(\\d+(?:\\.\\d+)?)\\s*mg\\s*/\\s*(\\d+(?:\\.\\d+)?)\\s*ml') AS mg_per_ml,
          apoc.text.regexGroups(n, '(\\d+(?:\\.\\d+)?)\\s*/\\s*(\\d+(?:\\.\\d+)?)') AS ratio
        WITH n,
          [x IN simple    | x[1] + ' ' + x[2]] +
          [x IN mg_per_ml | x[1] + ' mg / ' + x[2] + ' mL'] +
          [x IN ratio     | x[1] + '/' + x[2]] AS hits
        WITH n, apoc.coll.toSet(hits) AS strengths
        WHERE size(strengths) > 0
        RETURN n AS product, strengths[0..5] AS strengths
        ORDER BY n LIMIT $limit
        """
        rows = self._run_query(q, {"drug_name": drug_name, "limit": limit})
        return [{"product": r["product"], "strengths": r["strengths"]} for r in rows]

    def ancestry_path(self, drug_name: str, max_depth: int = 4) -> List[List[str]]:
        if not drug_name:
            return []
        q = f"""
        WITH toLower($drug_name) AS dlc
        MATCH (d:Concept {{name_lc: dlc}})
        MATCH p=(d)-[:RELATED_TO*1..{max_depth}]->(c:Concept)
        WHERE ALL(r IN relationships(p) WHERE r.rela='RB' OR r.type IN ['isa','is_a','parent'])
        RETURN [n IN nodes(p) | n.name] AS path
        ORDER BY size(path) ASC LIMIT 20
        """
        rows = self._run_query(q, {"drug_name": drug_name})
        return [r["path"] for r in rows]

_singleton_kb: Optional[KnowledgeBase] = None

def get_kb() -> KnowledgeBase:
    global _singleton_kb
    if _singleton_kb is None:
        _singleton_kb = KnowledgeBase()
    return _singleton_kb
