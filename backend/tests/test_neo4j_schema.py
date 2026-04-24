import os
import unittest
from neo4j import GraphDatabase, exceptions
from dotenv import load_dotenv
from graph.neo4j_schema import initialize_schema

class TestNeo4jSchema(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_dotenv()
        cls.uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        cls.user = os.getenv("NEO4J_USER", "neo4j")
        cls.password = os.getenv("NEO4J_PASSWORD", "password")
        
        try:
            cls.driver = GraphDatabase.driver(cls.uri, auth=(cls.user, cls.password))
            cls.driver.verify_connectivity()
            # Initialize schema for the test
            initialize_schema(cls.driver)
        except Exception as e:
            raise unittest.SkipTest(f"Neo4j not available: {e}")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "driver"):
            # Cleanup test data
            with cls.driver.session() as session:
                session.run("MATCH (n:Regulation {id: 'TEST-001'}) DELETE n")
            cls.driver.close()

    def test_uniqueness_constraint_regulation(self):
        """
        Tests that the uniqueness constraint on Regulation(id) is enforced.
        """
        with self.driver.session() as session:
            # 1. Clear any previous test data
            session.run("MATCH (n:Regulation {id: 'TEST-001'}) DELETE n")
            
            # 2. Create a node
            session.run("CREATE (:Regulation {id: 'TEST-001', title: 'Test Reg'})")
            
            # 3. Attempt to create exactly the same node
            with self.assertRaises(exceptions.ConstraintError) as cm:
                session.run("CREATE (:Regulation {id: 'TEST-001', title: 'Duplicate'})")
            
            print(f"DEBUG: Caught expected constraint error: {cm.exception}")

    def test_uniqueness_constraint_document(self):
        """
        Tests that the uniqueness constraint on Document(hash) is enforced.
        """
        with self.driver.session() as session:
            # 1. Clear previous
            session.run("MATCH (d:Document {hash: 'HASH-123'}) DELETE d")
            
            # 2. Create
            session.run("CREATE (:Document {hash: 'HASH-123', name: 'Doc A'})")
            
            # 3. Duplicate
            with self.assertRaises(exceptions.ConstraintError):
                session.run("CREATE (:Document {hash: 'HASH-123', name: 'Doc B'})")

if __name__ == "__main__":
    unittest.main()
