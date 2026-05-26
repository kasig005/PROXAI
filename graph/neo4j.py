from typing import List, Optional

from graph.constants import *
from graph.decorators import Singleton
from graph.logger import CustomLogger
from neo4j import GraphDatabase, Session

BATCH_SIZE = 500


@Singleton
class Neo4jConnector:
    """
    Class defining a connector for Neo4j.
    """

    def __init__(self, uri: str, user: str, pwd: str) -> None:
        self.__uri = uri
        self.__user = user
        self.__pwd = pwd
        self.__driver = None
        self.__logger = CustomLogger('ProvenanceTracker')

        try:
            self.__driver = GraphDatabase.driver(
                self.__uri, auth=(self.__user, self.__pwd))
        except Exception as e:
            self.__logger.error('Failed to create the driver:', e)

    def close(self) -> None:
        """
        Closes the Neo4j driver.
        """

        if self.__driver is not None:
            self.__driver.close()

    def create_session(self, db=None) -> Session:
        """
        Creates a Neo4j session.

        :param db: Optional parameter specifying the database to connect to.
        :return: A Neo4j session.
        """

        return self.__driver.session(database=db) if db is not None else self.__driver.session()




class Neo4jQueryExecutor:
    """
    Class that executes queries for Neo4j.
    Single-threaded batched writes — thread-pool approach was silently swallowing
    all exceptions in neo4j-python 5+/6+.
    """

    def __init__(self, connector) -> None:
        self.__connector = connector
        self.__logger = CustomLogger('ProvenanceTracker')

    def query(self, query: str, parameters: dict = None, db: str = None, session: Session = None) -> Optional[list]:
        """
        Executes a query. Uses an externally supplied session when provided,
        otherwise opens and closes its own session.
        """
        if not self.__connector:
            raise ValueError('Connector not initialized!')

        response = None
        external_session = session is not None

        try:
            if not external_session:
                session = self.__connector.create_session(db=db)
            response = session.run(query, parameters or {}).data()
        except Exception as e:
            self.__logger.error(f'Query failed: {e}\n  query: {query}\n  params keys: {list((parameters or {}).keys())}')
            print(f'[NEO4J ERROR] {e}\n  query snippet: {query[:120]}')
        finally:
            if not external_session and session is not None:
                session.close()
        return response

    def insert_data_batched(self, query: str, rows: List[any], **kwargs) -> None:
        """
        Writes rows to Neo4j in sequential batches of BATCH_SIZE.
        Opens a fresh session per batch so connection limits are respected.
        kwargs are passed as extra Cypher parameters alongside the batch rows.
        """
        if not rows:
            return

        for start in range(0, len(rows), BATCH_SIZE):
            batch = rows[start:start + BATCH_SIZE]
            params = {'rows': batch, **kwargs}
            self.query(query, parameters=params)

    # Keep old name as alias so nothing else breaks
    def insert_data_multiprocess(self, query: str, rows: List[any], **kwargs) -> None:
        self.insert_data_batched(query, rows, **kwargs)


class Neo4jQueries:
    """
    Class containing predefined queries for Neo4j.
    """

    def __init__(self, query_executor):
        self.__query_executor = query_executor
        self.logger = CustomLogger("ProvenanceTracker")

    def create_constraint(self, session=None) -> None:
        """
        Creates constraints for Neo4j nodes.

        :param session: An optional Neo4j session to use for executing the query.
        """

        query = '''DROP CONSTRAINT ''' + ACTIVITY_CONSTRAINT + ''''''
        self.__query_executor.query(query=query, parameters=None, session=session)

        query = '''DROP CONSTRAINT ''' +  ENTITY_CONSTRAINT
        self.__query_executor.query(query=query, parameters=None, session=session)

        query = '''DROP CONSTRAINT ''' + COLUMN_CONSTRAINT
        self.__query_executor.query(query=query, parameters=None, session=session)

        query = '''CREATE CONSTRAINT ''' + ACTIVITY_CONSTRAINT + \
                ''' FOR (a:''' + ACTIVITY_LABEL + \
                ''') REQUIRE a.id IS UNIQUE'''
        self.__query_executor.query(query=query, parameters=None, session=session)

        query = '''CREATE CONSTRAINT ''' + ENTITY_CONSTRAINT + \
                ''' FOR (e:''' + ENTITY_LABEL + \
                ''') REQUIRE e.id IS UNIQUE'''
        self.__query_executor.query(query=query, parameters=None, session=session)

        query = '''CREATE CONSTRAINT ''' + COLUMN_CONSTRAINT + \
                ''' FOR (c:''' + COLUMN_LABEL + \
                ''') REQUIRE c.id IS UNIQUE'''
        self.__query_executor.query(query=query, parameters=None, session=session)

    def delete_all(self, session=None):
        """
        Deletes all nodes and relationships in the database.

        :param session: An optional Neo4j session to use for executing the query.
        :return: The query result as a list or None if an error occurred.
        """

        query = '''
                MATCH (n)
                DETACH DELETE n
                '''

        self.logger.debug(msg=query)
        self.__query_executor.query(query, parameters=None, session=session)

    def add_activities(self, activities: List[any], session=None) -> None:
        """
        Adds activities to the database.

        :param activities: The activities to add.
        :param session: An optional Neo4j session to use for executing the query.
        :return: The query result as a list or None if an error occurred.
        """
        query = '''
                UNWIND $rows AS row
                CREATE (a:''' + ACTIVITY_LABEL + ''')
                SET a = row    
                '''
        self.logger.debug(msg=query)
        self.__query_executor.query(query, parameters={'rows': activities}, session=session)

    def add_entities(self, entities: List[any]) -> None:
        """
        Adds entities to the database.

        :param entities: The entities to add.
        :return: None
        """
        query = '''
                UNWIND $rows AS row
                CREATE (e:''' + ENTITY_LABEL + ''')
                SET e=row
                '''
        self.logger.debug(msg=query)
        self.__query_executor.insert_data_multiprocess(query=query, rows=entities)

    def add_columns(self, columns: List[any]) -> None:
        """
        Adds entities to the database.

        :param columns: The entities to add.
        :return: None
        """
        query = '''
                UNWIND $rows AS row
                CREATE (c:''' + COLUMN_LABEL + ''')
                SET c=row
                '''
        self.logger.debug(msg=query)
        self.__query_executor.insert_data_multiprocess(query=query, rows=columns)

    def udpate_entities(self, entities: List[any]) -> None:
        """
        Updates entities in the database.

        :param entities: The entities to update.
        :return: None
        """
        query = '''
                UNWIND $rows AS row
                MATCH (e:''' + ENTITY_LABEL + ''')
                WHERE e.id = row.id
                SET e=row
                '''
        self.logger.debug(msg=query)
        self.__query_executor.insert_data_multiprocess(query=query, rows=entities)

    def add_derivations(self, derivations: List[any]) -> None:
        """
        Adds derivations (relationships between entities) to the database.

        :param derivations: The derivations to add.
        :return: None
        """
        query = '''
                UNWIND $rows AS row
                MATCH (e1:''' + ENTITY_LABEL + ''' {id: row.gen})
                WITH e1, row
                MATCH (e2:''' + ENTITY_LABEL + ''' {id: row.used})
                MERGE (e1)-[:''' + DERIVATION_RELATION + ''']->(e2)
                '''
        self.logger.debug(msg=query)
        self.__query_executor.insert_data_multiprocess(query=query, rows=derivations)

    def add_derivations_columns(self, derivations: List[any]) -> None:
        """
        Adds derivations (relationships between entities) to the database.

        :param derivations: The derivations to add.
        :return: None
        """
        query = '''
                UNWIND $rows AS row
                MATCH (c1:''' + COLUMN_LABEL + ''' {id: row.gen})
                WITH c1, row
                MATCH (c2:''' + COLUMN_LABEL + ''' {id: row.used})
                MERGE (c1)-[:''' + DERIVATION_RELATION + ''']->(c2)
                '''
        self.logger.debug(msg=query)
        self.__query_executor.insert_data_multiprocess(query=query, rows=derivations)

    def add_relation_entities_to_column(self, relations: List[any]) -> None:
        """
        Adds relation to the column.

        :param relations: The derivations to add.
        :return: None
        """
        for relation in relations:
            column = relation[0]
            entities = relation[1]
            
            query = '''
                    UNWIND $rows AS row
                    MATCH (e:''' + ENTITY_LABEL + ''' {id: row})
                    WITH e
                    MATCH (a:''' + COLUMN_LABEL + ''' {id: $column})
                    MERGE (e)-[:''' + BELONGS_RELATION + ''']->(a)
                    '''
            self.logger.debug(msg=query)
            self.__query_executor.insert_data_multiprocess(query=query, rows=entities, column=column)


    def add_relations(self, relations: List[any]) -> None:
        """
        Adds relations (relationships between activities and entities) to the database.

        :param relations: The relations to add.
        :return: None
        """
        for relation in relations:
            generated = relation[0]
            used = relation[1]
            invalidated = relation[2]
            same = relation[3]
            act_id = relation[4]

            if same:
                invalidated = used

            query1 = '''
                    UNWIND $rows AS row
                    MATCH (e:''' + ENTITY_LABEL + ''' {id: row})
                    WITH e
                    MATCH (a:''' + ACTIVITY_LABEL + ''' {id: $act_id})
                    MERGE (a)-[:''' + USED_RELATION + ''']->(e)
                    '''
            query2 = '''
                    UNWIND $rows AS row
                    MATCH (e:''' + ENTITY_LABEL + ''' {id: row})
                    WITH e
                    MATCH (a:''' + ACTIVITY_LABEL + ''' {id: $act_id})
                    MERGE (e)-[:''' + GENERATION_RELATION + ''']->(a)
                    '''
            query3 = '''
                    UNWIND $rows AS row
                    MATCH (e:''' + ENTITY_LABEL + ''' {id: row})
                    WITH e
                    MATCH (a:''' + ACTIVITY_LABEL + ''' {id: $act_id})
                    MERGE (e)-[:''' + INVALIDATION_RELATION + ''']->(a)
                    '''

            self.logger.debug(msg=query1)
            self.logger.debug(msg=query2)
            self.logger.debug(msg=query3)

            self.__query_executor.insert_data_multiprocess(query=query1, rows=used, act_id=act_id)
            self.__query_executor.insert_data_multiprocess(query=query2, rows=generated, act_id=act_id)
            self.__query_executor.insert_data_multiprocess(query=query3, rows=invalidated, act_id=act_id)

    def add_relations_columns(self, relations: List[any]) -> None:
        """
        Adds relations (relationships between activities and entities) to the database.

        :param relations: The relations to add.
        :return: None
        """
        for relation in relations:
            generated = relation[0]
            used = relation[1]
            invalidated = relation[2]
            same = relation[3]
            act_id = relation[4]

            if same:
                invalidated = used

            query1 = '''
                    UNWIND $rows AS row
                    MATCH (c:''' + COLUMN_LABEL + ''' {id: row})
                    WITH c
                    MATCH (a:''' + ACTIVITY_LABEL + ''' {id: $act_id})
                    MERGE (a)-[:''' + USED_RELATION + ''']->(c)
                    '''
            query2 = '''
                    UNWIND $rows AS row
                    MATCH (c:''' + COLUMN_LABEL + ''' {id: row})
                    WITH c
                    MATCH (a:''' + ACTIVITY_LABEL + ''' {id: $act_id})
                    MERGE (c)-[:''' + GENERATION_RELATION + ''']->(a)
                    '''
            query3 = '''
                    UNWIND $rows AS row
                    MATCH (c:''' + COLUMN_LABEL + ''' {id: row})
                    WITH c
                    MATCH (a:''' + ACTIVITY_LABEL + ''' {id: $act_id})
                    MERGE (c)-[:''' + INVALIDATION_RELATION + ''']->(a)
                    '''

            self.logger.debug(msg=query1)
            self.logger.debug(msg=query2)
            self.logger.debug(msg=query3)

            self.__query_executor.insert_data_multiprocess(query=query1, rows=used, act_id=act_id)
            self.__query_executor.insert_data_multiprocess(query=query2, rows=generated, act_id=act_id)
            self.__query_executor.insert_data_multiprocess(query=query3, rows=invalidated, act_id=act_id)

    def add_next_operations(self, next_operations: List[any], session=None) -> None:
        """
        Adds relationships between activities representing the order in which they occur.

        :param next_operations: The next operations to add.
        :param session: An optional Neo4j session to use for executing the query.
        :return: None
        """
        query = ''' 
                UNWIND $next_operations AS next_operation
                MATCH (a1:''' + ACTIVITY_LABEL + ''' {id: next_operation.act_in_id})
                WITH a1, next_operation
                MATCH (a2:''' + ACTIVITY_LABEL + ''' {id: next_operation.act_out_id})
                MERGE (a1)-[:''' + NEXT_RELATION + ''']->(a2)
                '''

        self.logger.debug(msg=query)

        self.__query_executor.query(
            query, parameters={'next_operations': next_operations}, session=session)



class Neo4jFactory:

    def __init__(self):
        pass

    @staticmethod
    def create_neo4j_queries(uri: str, user: str, pwd: str) -> Neo4jQueries:
        """
        Creates Neo4jQueries object for executing queries on Neo4j.

        :param uri: The URI of the Neo4j database.
        :param user: The username for accessing the Neo4j database.
        :param pwd: The password for accessing the Neo4j database.
        :return: A Neo4jQueries object.
        """

        connector = Neo4jConnector(uri, user, pwd)
        query_executor = Neo4jQueryExecutor(connector)
        queries = Neo4jQueries(query_executor)
        return queries
