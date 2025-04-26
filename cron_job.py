from data_simulator import DataSimulator
from data_simulator.utils import get_config_path
from tqdm import tqdm

config_path = get_config_path("config.yaml")
simulator = DataSimulator(config_path)

tables = simulator.config.get('tables')

for table in tqdm(tables, desc="Processing tables", unit="table"):
    generated_data = simulator.generate_data_parallel(table, simulator.config.get('generate_rows'))
    if not generated_data:
        print(f"No data generated for table: {table}")
    simulator.db.batch_insert(table, generated_data)