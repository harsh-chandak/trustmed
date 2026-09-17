from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable
import os

URI = "bolt://localhost:7687"
AUTH = ("neo4j", "password123") 

def load_concepts(driver, mrconso_file_path):
    if not os.path.exists(mrconso_file_path):
        print(f"Error: The file was not found at the path: {mrconso_file_path}")
        return
    print("Starting Concept Loading")
    line_counter = 0
    with driver.session(database="neo4j") as session:
        session.run("CREATE CONSTRAINT concept_cui_unique IF NOT EXISTS FOR (c:Concept) REQUIRE c.cui IS UNIQUE;")
        
        query = """
        MERGE (c:Concept {cui: $cui})
        ON CREATE SET c.name = $name
        ON MATCH SET c.name = $name 
        """
        with open(mrconso_file_path, 'r', encoding='utf-8') as f:
            for line in f:
                fields = line.strip().split('|')
                if len(fields) > 11 and fields[11] in ['RXNORM', 'SNOMEDCT_US']:
                    cui = fields[0]
                    name = fields[14]
                    session.run(query, cui=cui, name=name)
                    line_counter += 1
                    if line_counter % 100000 == 0:
                        print(f"processed {line_counter} concepts")
    print(f"Finished Concept Loading. Total concepts loaded: {line_counter}\n")

def load_relationships(driver, mrrel_file_path):
    if not os.path.exists(mrrel_file_path):
        print(f"Error: The file was not found at the path: {mrrel_file_path}")
        return
    print("Starting Relationship Loading")
    line_counter = 0
    with driver.session(database="neo4j") as session:
        query = """
        MATCH (a:Concept {cui: $cui1})
        MATCH (b:Concept {cui: $cui2})
        MERGE (a)-[r:RELATED_TO]->(b)
        ON CREATE SET r.type = $type, r.rela = $rela
        """
        
        with open(mrrel_file_path, 'r', encoding='utf-8') as f:
            for line in f:
                fields = line.strip().split('|')
                if len(fields) > 7:
                    cui1 = fields[0]
                    rel_attribute = fields[3] 
                    cui2 = fields[4]
                    rel_type = fields[7]
                    
                    session.run(query, cui1=cui1, cui2=cui2, type=rel_type, rela=rel_attribute)
                    line_counter += 1
                    if line_counter % 100000 == 0:
                        print(f" processed {line_counter} relationships ")
    print(f" Finished Relationship Loading. Total relationships loaded: {line_counter} ")


if __name__ == "__main__":
    data_directory = "Data/META" 
    
    concepts_file = os.path.join(data_directory, "MRCONSO.RRF")
    relationships_file = os.path.join(data_directory, "MRREL.RRF")

    try:
        driver = GraphDatabase.driver(URI, auth=AUTH)
        driver.verify_connectivity()
        print("Database connection successful. Starting the full data ingestion process.")
        
        
        load_concepts(driver, concepts_file)
        
        
        load_relationships(driver, relationships_file)
        
        driver.close()
        print("\nAll data loading is complete.")

    except ServiceUnavailable:
        print("Error: Could not connect to the Neo4j database. Is it running?")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
