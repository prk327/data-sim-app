import yaml
from pathlib import Path
from faker import Faker
import random
from datetime import datetime, timedelta
from .db_operations import VerticaDB
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Iterable, Tuple
from threading import Lock

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
        self.faker = Faker()
        self.script_dir = Path(__file__).parent
        self.config_path = self.script_dir / config_path
        self.config = self._load_config()
        self.tables = self._load_table_configs()
        self.columns = self._load_column_configs()
        self.generated_data = {}
        self.reference_cache = {}
        self.cache_lock = Lock()  # Lock for thread safety
        self.db = VerticaDB(config_path)
        self.executor = ThreadPoolExecutor(max_workers=self.config.get('max_workers', 4))

    def _load_config(self):
        """
        Loads the configuration from the YAML file.
        """
        with open(self.config_path, 'r') as f:
            return yaml.safe_load(f)

    def _resolve_paths(self, key):
        """
        Resolves paths relative to the script directory.
        """
        return {
            k: (self.script_dir / v).resolve()
            for k, v in self.config[key].items()
        }

    def _load_table_configs(self):
        tables_dir = self._resolve_paths('yaml_path')['tables']
        table_configs = {}
        
        for table_file in tables_dir.glob('*.yaml'):
            with open(table_file) as f:
                table_data = yaml.safe_load(f)
                table_name = table_data['table_name']
                table_configs[table_name] = table_data
                
        return table_configs
        
    def _load_column_configs(self):
        columns_dir = self._resolve_paths('yaml_path')['columns']
        # Convert to Path object
        columnpath = Path(columns_dir)
        # Get the parent directory
        columns_dir = columnpath.parent
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

        # Add primary key column
        if 'primary_key' in table_config:
            pk_column = table_config['primary_key']
            schema[pk_column] = self.DEFAULT_PRIMARY_KEY_SCHEMA

        # Add other columns
        for col in table_config.get('columns', []):
            if col in self.columns:
                schema[col] = self.columns[col]
            else:
                schema[col] = self.DEFAULT_COLUMN_SCHEMA
                print(f"Warning: Using default schema for column {col} in table {table_name}")

        # Add foreign key columns
        for fk in table_config.get('foreign_keys', []):
            fk_column = fk['column']
            ref_table = fk['references']['table']
            ref_column = fk['references']['column']

            # Fetch foreign key definition from referenced table
            if ref_table in self.tables:
                ref_schema = self.get_table_schema(ref_table)
                if ref_column in ref_schema:
                    schema[fk_column] = {
                        "type": ref_schema[ref_column]["type"],  # Use the same type as the referenced column
                        "constraints": [f"foreign_key: {ref_table}.{ref_column}"],
                        "simulation": fk.get('simulation', {})
                    }
                else:
                    # If referenced column not found, use default schema
                    schema[fk_column] = {
                        "type": "INT",  # Default type for foreign keys
                        "constraints": [f"foreign_key: {ref_table}.{ref_column}"],
                        "simulation": fk.get('simulation', {})
                    }
                    print(f"Warning: Referenced column {ref_column} not found in table {ref_table}. Using default schema.")
            else:
                # If referenced table not found, use default schema
                schema[fk_column] = {
                    "type": "INT",  # Default type for foreign keys
                    "constraints": [f"foreign_key: {ref_table}.{ref_column}"],
                    "simulation": fk.get('simulation', {})
                }
                print(f"Warning: Referenced table {ref_table} not found. Using default schema.")
        
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
            condition = f"rowid > {last_id}" if last_id else None
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
            last_id = chunk[-1]
        
        # Cache the full list
        self.reference_cache[cache_key] = data
        return data  # Return a list, not a generator!

    def generate_data_parallel(self, table_name, num_records, batch_size=1000):
        # Pre-fetch all reference data first
        self.pre_fetch_references(table_name)
        
        # Parallel generation
        futures = []
        for i in range(0, num_records, batch_size):
            futures.append(
                self.executor.submit(
                    self._generate_batch,
                    table_name,
                    min(batch_size, num_records - i)
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
        sim_config = col_config.get('simulation', {})
        
        if not sim_config:
            raise ValueError("No simulation configuration found for the column.")

        sim_type = sim_config.get('type')
        
        if sim_type == 'sequence':
            return self._handle_sequence(col_config)
            
        elif sim_type == 'faker':
            provider = sim_config.get('provider')
            method = sim_config.get('method')
            params = sim_config.get('params', {})
            
            if not method:
                print(sim_config)
                raise ValueError("Faker configuration must include 'method'.")
            
            # Handle special cases like 'words'
            if provider == 'word' and method == 'words':
                return ' '.join(self.faker.words(**params))

            # Handle cases where the method is directly available on the Faker instance
            if hasattr(self.faker, method):
                return getattr(self.faker, method)(**params)

            # Handle cases where the method is part of a provider
            if provider:
                faker_provider = getattr(self.faker, provider)
                if hasattr(faker_provider, method):
                    return getattr(faker_provider, method)(**params)
                else:
                    raise ValueError(f"Method '{method}' not found in provider '{provider}'.")
            else:
                raise ValueError(f"Method '{method}' not found in Faker instance.")
                
        elif sim_type == 'enum':
            values = sim_config.get('values')
            weights = sim_config.get('weights')
            
            if not values:
                raise ValueError("Enum configuration must include 'values'.")
            
            return random.choices(values, weights=weights, k=1)[0]
            
        elif sim_type == 'random':
            return self._generate_random_value(sim_config)
            
        elif sim_type == 'date':
            return self._generate_date(sim_config)
            
        else:
            raise ValueError(f"Unsupported simulation type: {sim_type}")

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
            value = random.normalvariate(mean, std_dev)
            # Clip to min and max if provided
            if 'min' in params and 'max' in params:
                value = max(params['min'], min(params['max'], value))
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
    simulator = DataSimulator("config/config.yaml")

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