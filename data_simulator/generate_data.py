import yaml
from pathlib import Path
from faker import Faker
import random
from data_simulator.db_operations import VerticaDB
from concurrent.futures import as_completed
from typing import List, Dict, Iterable

class DataSimulator:

    DEFAULT_PRIMARY_KEY_SCHEMA = {
        "type": "INT",
        "constraints": ["primary_key", "auto_increment"],
        "simulation": {
            "type": "sequence",
            "start": 1000,
            "step": 1
        }
    }

    DEFAULT_COLUMN_SCHEMA = {
            "type": "VARCHAR(255)",
            "constraints": [],
            "simulation": {
                "type": "faker",
                "provider": "word",
                "method": "words"
            }
        }
        
        
    def __init__(self, config_path: dict):
        """
        Initialize DataSimulator with flexible path handling.
        
        Args:
            config_path: Can be either:
                - Absolute path (/path/to/config.yaml)
                - Relative path from project root (config/config.yaml)
                - Relative path from calling script
        """
        self.faker = Faker()
        abs_config_path = str(Path(__file__).parent.parent / config_path)
        self.db = VerticaDB(abs_config_path)  # Central resource hub
        
        # Reuse resources from VerticaDB instance
        self.config = self.db.config
        self.executor = self.db.executor
        self.pool_lock = self.db.pool_lock
        
        # Load configurations using VerticaDB's path resolution
        self.tables = self._load_table_configs()
        self.columns = self._load_column_configs()
        self.generated_data = {}
        self.reference_cache = {}

    def _load_config(self, config_path: str):
        """Config already loaded by VerticaDB"""
        return self.db.config

    def _resolve_path(self, path_key: str) -> Path:
        """Reuse VerticaDB's path resolution strategy"""
        return self.db._resolve_config_path(self.config['yaml_path'][path_key])

    def _load_table_configs(self):
        """Load table configurations using shared path resolution"""
        tables_dir = self._resolve_path('tables')
        table_configs = {}
        
        for table_file in tables_dir.glob('*.yaml'):
            with open(table_file) as f:
                table_data = yaml.safe_load(f)
                table_name = table_data['table_name']
                table_configs[table_name] = table_data
                
        return table_configs
        
    def _load_column_configs(self):
        """Load column configurations using shared path resolution"""
        columns_dir = self._resolve_path('columns')
        column_configs = {}

        for column_file in columns_dir.glob('*.yaml'):
            with open(column_file) as f:
                column_data = yaml.safe_load(f)
                column_configs.update(column_data.get('columns', {}))

        return column_configs
        
    def get_table_schema(self, table_name):
        if table_name not in self.tables:
            raise ValueError(f"Table {table_name} not found")
        
        table_config = self.tables[table_name]
        schema = {}
        seen_columns = set()  # To track duplicate columns

        # Add primary key column
        if 'primary_key' in table_config:
            pk_column = table_config['primary_key']
            if pk_column in seen_columns:
                print(f"Warning: Duplicate primary key column '{pk_column}' in table '{table_name}' - keeping first occurrence")
            else:
                schema[pk_column] = self.DEFAULT_PRIMARY_KEY_SCHEMA
                seen_columns.add(pk_column)
        # Add other columns
        for col in table_config.get('columns', []):
            if col in seen_columns:
                print(f"Warning: Duplicate column '{col}' in table '{table_name}' - skipping")
                continue
                
            if col in self.columns:
                schema[col] = self.columns[col]
            else:
                schema[col] = self.DEFAULT_COLUMN_SCHEMA
                print(f"Warning: Using default schema for column '{col}' in table '{table_name}'")
            seen_columns.add(col)
        # Add foreign key columns
        for fk_column in table_config.get('foreign_keys', []):
            
            if fk_column in seen_columns:
                print(f"Warning: Duplicate foreign key column '{fk_column}' in table '{table_name}' - skipping")
                continue
                
            try:
                ref_table = table_config['foreign_keys'][fk_column]['references']['table']
                ref_column = table_config['foreign_keys'][fk_column]['references']['column']
            except:
                print(f"Warning: foreign key '{fk_column}' is defined in table '{table_name}' without references")

            # Fetch foreign key definition from referenced table
            if ref_table in self.tables:
                ref_schema = self.get_table_schema(ref_table)
                if ref_column in ref_schema:
                    schema[fk_column] = {
                        "type": ref_schema[ref_column]["type"],  # Use the same type as the referenced column
                        "constraints": [f"foreign_key: {ref_table}.{ref_column}"],
                        "simulation": {
                                        "type": "reference",
                                        "table": ref_table,
                                        "column": ref_column
                                    }
                    }
                else:
                    print(f"Warning: foreign key Referenced column '{ref_column}' not found in table '{ref_table}'.")
            else:
                print(f"Warning: foreign key Referenced table '{ref_table}' not found.")
            
            seen_columns.add(fk_column)
       
        return schema
    
    def _fetch_reference_data(self, ref_table, ref_column, chunk_size=1000):
        cache_key = (ref_table, ref_column)
        
        # Check cache first
        if cache_key in self.reference_cache:
            return self.reference_cache[cache_key]
        
        # Fetch data in chunks and store as a list
        data = []
        last_id = None
        while True:
            condition = None if not last_id else f"rowid > {last_id} and rowid < {chunk_size}" if last_id <= chunk_size else "rowid IS NULL"
            chunk = [
                row[0] for row in self.db.read(
                    ref_table, 
                    columns=ref_column, 
                    condition=condition, 
                    limit=chunk_size
                )
            ]
            if not chunk:
                break
            data.extend(chunk)
            if not last_id:
                last_id = len(chunk) - 1
            else:
                last_id += len(chunk)
        
        # Cache the full list
        self.reference_cache[cache_key] = data
        return data  # Return a list, not a generator!

    def generate_data_parallel(self, table_name, num_records, batch_size=1000):
        # Pre-fetch all reference data first
        self.pre_fetch_references(table_name)

        # Calculate the number of full batches and the remaining records
        full_batches = num_records // batch_size
        remaining_records = num_records % batch_size
        
        # Parallel generation
        futures = []
        
        # Submit full batches
        for _ in range(full_batches):
            futures.append(
                self.executor.submit(
                    self._generate_batch,
                    table_name,
                    batch_size
                )
            )
        
        # Submit remaining records if any
        if remaining_records > 0:
           futures.append(
                self.executor.submit(
                    self._generate_batch,
                    table_name,
                    remaining_records
                )
            )
        results = []
        for future in as_completed(futures):
            results.extend(future.result())
        return results
    
    def pre_fetch_references(self, table_name):
        schema = self.get_table_schema(table_name)
        for col_config in schema.values():
            if col_config['simulation'].get('type') == 'reference':
                ref_table = col_config['simulation']['table']
                ref_column = col_config['simulation']['column']
                self._fetch_reference_data(ref_table, ref_column)
    
    def _generate_batch(self, table_name, batch_size):
        # Reuse pre-fetched reference data
        schema = self.get_table_schema(table_name)
        return [self._generate_record(schema) for _ in range(batch_size)]
    
    def _generate_record(self, schema):
        record = {}
        for col, col_config in schema.items():
            if col_config['simulation'].get('type') == 'reference':
                ref_table = col_config['simulation']['table']
                ref_column = col_config['simulation']['column']
                ref_data = self.reference_cache[(ref_table, ref_column)]  # Get cached list
                record[col] = random.choice(ref_data)  # Works with lists
            else:
                record[col] = self._generate_column_data(col_config)
        return record

    def _generate_column_data(self, col_config):
        """
        Generates data for a column with optional null values.
        
        Args:
            col_config: Column configuration dictionary containing:
                - simulation: Simulation configuration
                - null_probability: Probability of generating null (0-1, default 0)
                
        Returns:
            Generated data or None (for null values)
        """
        # Check for null probability (default to 0 if not specified)
        null_prob = col_config.get('null_probability', 0)

         # Generate null value if probability triggers
        if null_prob > 0 and random.random() < null_prob:
            return None

        sim_config = col_config.get('simulation', {})
        
        if not sim_config:
            raise ValueError(f"No simulation configuration found for the column: {col_config.get('field_name')}")

        sim_type = sim_config.get('type')

        try:
        
            if sim_type == 'sequence':
                return self._handle_sequence(col_config)
                
            elif sim_type == 'faker':
                provider = sim_config.get('provider')
                method = sim_config.get('method')
                params = sim_config.get('params', {})
                
                if not method:
                    raise ValueError(f"Faker configuration must include 'method' for column: {col_config.get('field_name')}")
                
                # Handle special cases like 'words'
                if provider == 'word' and method == 'words':
                    return ' '.join(self.faker.words(**params))

                # Handle cases where the method is directly available on the Faker instance
                if hasattr(self.faker, method):
                    result = getattr(self.faker, method)(**params)
                    return None if result is None else str(result)  # Convert to string unless None

                # Handle cases where the method is part of a provider
                if provider:
                    faker_provider = getattr(self.faker, provider)
                    if hasattr(faker_provider, method):
                        result = getattr(faker_provider, method)(**params)
                        return None if result is None else str(result)
                    raise ValueError(f"Method '{method}' not found in provider '{provider}'")
                raise ValueError(f"Method '{method}' not found in Faker instance")
                    
            elif sim_type == 'enum':
                values = sim_config.get('values')
                weights = sim_config.get('weights')
                
                if not values:
                    raise ValueError("Enum configuration must include 'values'.")
                
                return random.choices(values, weights=weights, k=1)[0]
                
            elif sim_type == 'random':
                return self._generate_random_value(sim_config)
                
            elif sim_type == 'date':
                date_value = self._generate_date(sim_config)
                return date_value.strftime('%Y-%m-%d %H:%M:%S') if date_value else None

            elif sim_type == 'constant':
                return sim_config.get('value')
                
            else:
                raise ValueError(f"Unsupported simulation type: {sim_type}")

        except Exception as e:
            self.logger.error(f"Error generating data for {col_config.get('field_name')}: {str(e)}")
            return None  # Fallback to null on error

    def _handle_sequence(self, col_config):
        sim_config = col_config.get('simulation', {})
        start = sim_config.get('start', 0)
        step = sim_config.get('step', 1)
        
        if not hasattr(self, '_sequence_counter'):
            self._sequence_counter = start
        else:
            self._sequence_counter += step
        
        return self._sequence_counter

    def _generate_random_value(self, sim_config):
        distribution = sim_config.get('distribution')
        params = sim_config.get('params', {})
        
        if distribution == 'normal':
            mean = params.get('mean', 0)
            std_dev = params.get('std_dev', 1)
            min_val = params.get('min', float('-inf'))
            max_val = params.get('max', float('inf'))
            
            # Generate values until we get one within bounds (with max attempts to prevent infinite loops)
            max_attempts = 100
            for _ in range(max_attempts):
                value = random.normalvariate(mean, std_dev)
                if min_val <= value <= max_val:
                    break
            else:
                # If we can't get a value within bounds after max attempts, clip to nearest bound
                value = max(min_val, min(max_val, mean))
            
            # Round to precision if provided
            precision = params.get('precision')
            if precision is not None:
                value = round(value, precision)
            return value
            
        elif distribution == 'uniform':
            min_val = params.get('min', 0)
            max_val = params.get('max', 1)
            value = random.uniform(min_val, max_val)
            # Round to precision if provided
            precision = params.get('precision')
            if precision is not None:
                value = round(value, precision)
            return value
            
        elif distribution == 'choice':
            choices = params.get('choices', [])
            return random.choice(choices)
            
        else:
            raise ValueError(f"Unsupported random distribution: {distribution}")
            
    def _generate_date(self, sim_config):
        params = sim_config.get('params', {})
        start_date = params.get('start_date', '-1y')
        end_date = params.get('end_date', 'now')
        
        return self.faker.date_time_between(start_date=start_date, end_date=end_date)

    def convert_list_of_dicts_to_tuples(self, data: List[Dict]) -> Dict[str, Iterable]:
        # Extract column names from the first dictionary
        columns = list(data[0].keys())
        
        # Extract values from each dictionary and convert them to tuples
        values = [tuple(d.values()) for d in data]
        
        # Return the result in the desired format
        return columns, values

    def yield_data(self, listTuples):
        for i in listTuples:
            yield i
        yield None  # Sentinel value to signal end of data
# Usage Example
if __name__ == "__main__":
    from data_simulator.utils import get_config_path
    config_path = get_config_path("config.yaml")
    simulator = DataSimulator(config_path)

    products = simulator.generate_data_parallel('products', 500)
    simulator.db.batch_insert('products', products)

    # Generate users
    users = simulator.generate_data_parallel('users', 1000)
    simulator.db.batch_insert('users', users)
    # print(users)
    
    # Generate orders referencing users
    orders = simulator.generate_data_parallel('orders', 2000)
    
    # Insert into Vertica
    # db = VerticaDB()  # From previous module
    simulator.db.batch_insert('orders', orders)