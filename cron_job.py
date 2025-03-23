from data_simulator import DataSimulator
import yaml

# Load Vertica config
# with open('/app/data_simulator/config/config.yaml') as f:
#     config = yaml.safe_load(f)

simulator = DataSimulator('/app/data_simulator/config/config.yaml')

for table in simulator.config.get('tables'):
    generated_data = simulator.generate_data_parallel(table, simulator.config.get('generate_rows'))
    simulator.db.batch_insert(table, generated_data)