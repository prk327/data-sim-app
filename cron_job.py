from data_simulator import DataSimulator

simulator = DataSimulator('config/config.yaml')

for table in simulator.config.get('tables'):
    generated_data = simulator.generate_data_parallel(table, simulator.config.get('generate_rows'))
    simulator.db.batch_insert(table, generated_data)