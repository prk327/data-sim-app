import yaml
from pathlib import Path
from vertica_python import connect
from threading import Lock
from jinja2 import Template
from io import StringIO
import csv
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class VerticaDB:
    def __init__(self, config_path):
        self.script_dir = Path(__file__).parent
        self.config_path = self.script_dir / config_path
        self.config = self._load_config()
        self.schema = self.config.get('schema', 'public')  # Default schema is 'public'
        self.connection_pool = []
        self.pool_lock = Lock()
        self._init_pool()
        self.sql_templates = self._load_sql_templates()
        self.executor = ThreadPoolExecutor(max_workers=self.config.get('max_workers', 4))

    def _load_config(self):
        """
        Loads the configuration from the YAML file.
        """
        with open(self.config_path, 'r') as f:
            return yaml.safe_load(f)['vertica']

    def _load_sql_templates(self):
        templates = {}
        sql_dir = self.script_dir / 'sql'
        for sql_file in sql_dir.glob('*.sql'):
            with open(sql_file) as f:
                templates[sql_file.stem] = Template(f.read())
        return templates

    def _create_connection(self):
        return connect(
            host=self.config['host'],
            port=self.config['port'],
            user=self.config['user'],
            password=self.config['password'],
            database=self.config['database'],
            tlsmode='disable'
        )

    def _init_pool(self):
        with self.pool_lock:
            for _ in range(self.config['pool_size']):
                self.connection_pool.append(self._create_connection())

    def get_connection(self):
        with self.pool_lock:
            if not self.connection_pool:
                return self._create_connection()
            return self.connection_pool.pop()

    def release_connection(self, conn):
        with self.pool_lock:
            if len(self.connection_pool) < self.config['pool_size']:
                self.connection_pool.append(conn)
            else:
                logger.info(f"Connection pool size: {len(self.connection_pool)}")
                conn.close()

    def execute_query(self, template_name, params=None, data=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            template = self.sql_templates[template_name]
            query = template.render(**(params or {}))
            # logger.info(f"Executing query: {query}")
            cursor.execute(query, data)
            if template_name == 'read':
                return cursor.fetchall()
            else:
                conn.commit()
                return cursor.rowcount
        except Exception as e:
            conn.rollback()
            logger.error(f"Error executing query: {e}")
            raise e
        finally:
            cursor.close()
            self.release_connection(conn)

    def execute_parallel(self, queries):
        futures = []
        for query in queries:
            futures.append(self.executor.submit(self.execute_query, **query))
        results = []
        for future in as_completed(futures):
            results.append(future.result())
        return results

    # CRUD Operations
    def insert(self, table_name, data):
        params = {
            'schema': self.schema,  # Pass schema to the template
            'table_name': table_name,
            'columns': ', '.join(data.keys()),
            'placeholders': ', '.join([f':{k}' for k in data.keys()])
        }
        return self.execute_query('insert', params, data)

    def read(self, table_name, columns, condition=None, limit=1000):
        params = {
            'schema': self.schema,  # Pass schema to the template
            'table_name': table_name,
            'columns': columns,
            'condition': condition,
            'limit': limit
        }
        return self.execute_query('read', params)

    def update(self, table_name, data, condition):
        params = {
            'schema': self.schema,  # Pass schema to the template
            'table_name': table_name,
            'set_clause': ', '.join([f"{k} = :{k}" for k in data.keys()]),
            'condition': condition
        }
        return self.execute_query('update', params, data)

    def delete(self, table_name, condition):
        params = {
            'schema': self.schema,  # Pass schema to the template
            'table_name': table_name,
            'condition': condition
        }
        return self.execute_query('delete', params)

    def batch_insert(self, table_name, data, batch_size=1000):
        """
        Bulk insert data using Vertica's COPY command
        Args:
            table_name (str): Name of the table
            data (list[dict]): List of dictionaries to insert
            batch_size (int): Number of records per batch
        Returns:
            int: Total number of inserted rows
        """
        if not data:
            return 0

        conn = self.get_connection()
        # if conn.closed:
        #     raise ValueError("Connection is closed")
            
        cursor = conn.cursor()
        total_rows = 0
        
        try:
            # Check transaction state
            if conn.autocommit:
                # Disable autocommit
                conn.autocommit = False
            
            # Split data into batches
            for i in range(0, len(data), batch_size):
                batch = data[i:i+batch_size]
                columns = list(batch[0].keys())
                
                # Create in-memory CSV buffer
                csv_buffer = StringIO()
                writer = csv.writer(csv_buffer, delimiter=',', quoting=csv.QUOTE_MINIMAL)
                
                for record in batch:
                    writer.writerow([record.get(col) for col in columns])
                
                csv_data = csv_buffer.getvalue()
                csv_buffer.seek(0)

                # Build COPY command with schema
                copy_query = f"""
                    COPY {self.schema}.{table_name} ({', '.join(columns)})
                    FROM STDIN 
                    DELIMITER ',' 
                    ENCLOSED BY '"'
                    NULL ''
                    SKIP 0 
                    REJECTMAX 0
                    DIRECT
                """
                
                # Execute COPY command
                cursor.copy(copy_query, csv_data)
                total_rows += len(batch)
                csv_buffer.close()
                
            # Explicitly commit the transaction
            conn.commit()
            return total_rows
            
        except Exception as e:
            # Rollback on error
            if not conn.closed:
                conn.rollback()
            logger.error(f"Error during batch insert: {e}")
            raise e
        finally:
            # Reset autocommit to default
            if not conn.closed:
                conn.autocommit = True
                cursor.close()
                self.release_connection(conn)

# Example Usage
if __name__ == "__main__":
    db = VerticaDB("config/config.yaml")
    
    # Insert example
    db.insert('users', {'username': 'John Doe', 'created_at': "2024-05-24"})
    
    # Read example
    results = db.read('users', columns='*', condition='created_at > 25')
    print(results)
    
    # Update example
    db.update('users', {'age': 31}, condition="name = 'John Doe'")
    
    # Delete example
    db.delete('users', condition="name = 'John Doe'")