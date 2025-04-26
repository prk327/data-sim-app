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
        """
        Initialize VerticaDB with flexible path handling.
        
        Args:
            config_path: Can be either:
                - Absolute path (/path/to/config.yaml)
                - Relative path from project root (config/config.yaml)
                - Relative path from calling script
        """
        # Try multiple path resolution strategies
        self.config_path = self._resolve_config_path(config_path)
        self.config = self._load_config()
        self.schema = self.config['vertica'].get('schema', 'public')
        self.connection_pool = []
        self.pool_lock = Lock()
        self._init_pool()
        self.sql_templates = self._load_sql_templates()
        self.executor = ThreadPoolExecutor(max_workers=self.config['vertica'].get('max_workers', 4))

    def _resolve_config_path(self, config_path):
        """Resolve config path using multiple strategies for installed packages"""
        path = Path(config_path)
        
        # 1. Check if absolute path exists
        if path.is_absolute() and path.exists():
            return path
        
        # 2. Try relative to package installation
        package_dir = Path(__file__).parent.parent
        package_path = package_dir / config_path
        if package_path.exists():
            return package_path
        
        # 3. Try relative to user's working directory
        cwd_path = Path.cwd() / config_path
        if cwd_path.exists():
            return cwd_path
        
        # 4. Try common config locations
        common_locations = [
            Path("/etc/data_simulator") / config_path,
            Path.home() / ".config" / "data_simulator" / config_path,
            Path.home() / "data_simulator" / config_path
        ]
        
        for location in common_locations:
            if location.exists():
                return location
        
        raise FileNotFoundError(
            f"Could not locate config file at: {config_path}\n"
            f"Tried locations:\n"
            f"- Package relative: {package_path}\n"
            f"- Working dir: {cwd_path}\n"
            f"- Common locations: {common_locations}"
        )

    def _find_project_root(self):
        """Find project root by looking for setup.py or other marker files"""
        current = Path(__file__).parent
        while current != current.parent:
            if (current / 'setup.py').exists() or (current / 'pyproject.toml').exists():
                return current
            current = current.parent
        return None

    def _load_config(self):
        """
        Loads the configuration from the YAML file.
        """
        with open(self.config_path, 'r') as f:
            return yaml.safe_load(f)

    def _load_sql_templates(self):
        """Load SQL templates from sql directory"""
        # Try multiple locations for SQL templates
        possible_sql_dirs = [
            Path(__file__).parent / 'sql',              # Relative to this file
            self.config_path.parent / 'sql',            # Relative to config
            self._find_project_root() / 'data_simulator' / 'sql'  # Project structure
        ]
        
        templates = {}
        for sql_dir in possible_sql_dirs:
            if sql_dir.exists():
                for sql_file in sql_dir.glob('*.sql'):
                    with open(sql_file) as f:
                        templates[sql_file.stem] = Template(f.read())
                break
        else:
            raise FileNotFoundError("Could not locate SQL templates directory")
        
        return templates

    def _create_connection(self):
        return connect(
            host=self.config['vertica']['host'],
            port=self.config['vertica']['port'],
            user=self.config['vertica']['user'],
            password=self.config['vertica']['password'],
            database=self.config['vertica']['database'],
            tlsmode='disable'
        )

    def _init_pool(self):
        with self.pool_lock:
            for _ in range(self.config['vertica']['pool_size']):
                self.connection_pool.append(self._create_connection())

    def get_connection(self):
        with self.pool_lock:
            if not self.connection_pool:
                return self._create_connection()
            return self.connection_pool.pop()

    def release_connection(self, conn):
        with self.pool_lock:
            if len(self.connection_pool) < self.config['vertica']['pool_size']:
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
    from data_simulator.utils import get_config_path
    config_path = get_config_path("config.yaml")
    db = VerticaDB(config_path)
    
    # Insert example
    db.insert('CDR_GI', {'TIME_STAMP': '2025-04-25 15:09:54.644', 'MEASURING_PROBE_TYPE': 'sms voice network', 'START_TIME': '2025-04-25 15:09:47.870', 'SESSION_ID': '432216', 'MEASURING_PROBE_NAME': 'device network sms'})
    db.insert('CDR_GI', {'TIME_STAMP': '2025-04-25 15:10:24.593', 'MEASURING_PROBE_TYPE': 'mms subscription voice', 'START_TIME': '2025-04-25 15:09:58.326', 'SESSION_ID': '404357', 'MEASURING_PROBE_NAME': 'mms sms voice'})
    db.insert('CDR_GI', {'TIME_STAMP': '2025-04-25 15:09:29.470', 'MEASURING_PROBE_TYPE': 'data roaming network', 'START_TIME': '2025-04-25 15:11:15.850', 'SESSION_ID': '455778', 'MEASURING_PROBE_NAME': 'device network sms'})
    
    # Read example
    results = db.read('CDR_GI', columns='TIME_STAMP, MEASURING_PROBE_TYPE, START_TIME, SESSION_ID, MEASURING_PROBE_NAME', condition='SESSION_ID = 404357')
    print(results)
    
    # Update example
    db.update('CDR_GI', {'MEASURING_PROBE_NAME': 'call sms data'}, condition="SESSION_ID = 432216")
    
    # Delete example
    db.delete('CDR_GI', condition="SESSION_ID = 404357")