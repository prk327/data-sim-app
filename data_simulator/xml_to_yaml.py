import yaml
from pathlib import Path
import xml.etree.ElementTree as ET
import logging
import copy

class ConfigGenerator:
    def __init__(self, config_path):
        """
        Initializes the ConfigGenerator with the path to the config file.
        """
        self.script_dir = Path(__file__).parent
        self.config_path = self.script_dir / config_path
        self.config = self._load_config()
        self._setup_logging()

    def _load_config(self):
        """
        Loads the configuration from the YAML file.
        """
        with open(self.config_path, 'r') as f:
            return yaml.safe_load(f)

    def _setup_logging(self):
        """
        Configures logging for the module.
        """
        logging.basicConfig(
            level=logging.WARNING,
            format="%(asctime)s - %(levelname)s - %(message)s",
            filename="missing_types.log"
        )
        self.logger = logging.getLogger(__name__)

    def _resolve_paths(self, key):
        """
        Resolves paths relative to the script directory.
        """
        return {
            k: (self.script_dir / v).resolve()
            for k, v in self.config[key].items()
        }

    def _extract_table_fields(self, cdr_template_path, tables_to_process):
        """
        Extracts field names for each table where include_in_db="true".
        """
        # Define namespaces
        namespaces = {
            'ns': 'http://radcom.com/OmniQCdrs.xsd',
            'xt': 'http://radcom.com/XSDTypes.xsd'
        }

        # Parse XML with namespaces
        tree = ET.parse(cdr_template_path)
        root = tree.getroot()

        # Extract all tables (cdr elements)
        all_tables = root.findall('.//ns:cdr', namespaces)

        # Map table names to their field names
        table_fields = {}
        for table_element in all_tables:
            table_name = table_element.attrib.get('table-name', '')
            if table_name not in tables_to_process:
                continue  # Skip tables not in the config list

            # Extract field names where include_in_db="true"
            fields = [
                field.attrib['name']
                for field in table_element.findall('.//xt:field', namespaces)
                if field.attrib.get('include_in_db') == 'true'
            ]
            table_fields[table_name] = fields

        return table_fields

    def _extract_column_names(self, fields_xml_path):
        """
        Extracts column names from fields.xml.
        """
        tree = ET.parse(fields_xml_path)
        root = tree.getroot()

        # Map field names to column names
        field_to_column = {}
        for field in root.findall('.//field'):
            field_name = field.attrib.get('name', '')
            column_name = field.find('.//database/column-name')
            if column_name is not None and column_name.text:
                field_to_column[field_name] = column_name.text

        return field_to_column

    def generate_table_configs(self):
        """
        Generates YAML configurations for tables from the CDR template XML.
        Uses column names from fields.xml.
        """
        xml_paths = self._resolve_paths('xml_path')
        yaml_paths = self._resolve_paths('yaml_path')
        tables_to_process = self.config['tables']

        # Process CDR template XML
        cdr_template_path = xml_paths['cdr_template']
        if not cdr_template_path.exists():
            raise FileNotFoundError(f"CDR template XML not found: {cdr_template_path}")

        # Process fields XML
        fields_xml_path = xml_paths['fields_template']
        if not fields_xml_path.exists():
            raise FileNotFoundError(f"Fields XML not found: {fields_xml_path}")

        # Extract table fields and column names
        table_fields = self._extract_table_fields(cdr_template_path, tables_to_process)
        field_to_column = self._extract_column_names(fields_xml_path)

        # Generate YAML for each table
        for table_name, fields in table_fields.items():
            # Map field names to column names
            columns = [
                field_to_column.get(field, field)  # Use field name as fallback
                for field in fields
            ]

            # Extract primary key from the table element
            tree = ET.parse(cdr_template_path)
            root = tree.getroot()
            namespaces = {
                'ns': 'http://radcom.com/OmniQCdrs.xsd',
                'xt': 'http://radcom.com/XSDTypes.xsd'
            }
            table_element = root.find(f'.//ns:cdr[@table-name="{table_name}"]', namespaces)
            if table_element is not None:
                primary_key_field = table_element.attrib.get('unique-field', '').replace(' ', '_')
                primary_key = field_to_column.get(primary_key_field, primary_key_field)
            else:
                primary_key = ''  # Fallback if primary key is not found

            # Build YAML config
            yaml_config = {
                'table_name': table_name,
                'primary_key': primary_key,  # Use the extracted primary key
                'columns': columns
            }

            # Write to YAML file
            output_path = yaml_paths['tables'] / f"{table_name}.yaml"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'w') as f:
                yaml.dump(yaml_config, f, default_style=None, default_flow_style=False)

    def generate_columns_config(self):
        """
        Generates YAML configurations for columns from the fields XML.
        Only includes fields that belong to the specified tables and have include_in_db="true".
        """
        xml_paths = self._resolve_paths('xml_path')
        yaml_paths = self._resolve_paths('yaml_path')
        tables_to_process = self.config['tables']

        # Extract table fields from CDR template
        cdr_template_path = xml_paths['cdr_template']
        if not cdr_template_path.exists():
            raise FileNotFoundError(f"CDR template XML not found: {cdr_template_path}")
        table_fields = self._extract_table_fields(cdr_template_path, tables_to_process)

        # Load type mapping and simulation config
        type_mapping = self.config.get('type_mapping', {})
        simulation_config = self.config.get('simulation_config', {})

        # Parse the fields XML
        fields_xml_path = xml_paths['fields_template']
        if not fields_xml_path.exists():
            raise FileNotFoundError(f"Fields XML not found: {fields_xml_path}")

        tree = ET.parse(fields_xml_path)
        root = tree.getroot()

        # Extract fields and their details
        columns = {}
        for field in root.findall('.//field'):
            field_name = field.attrib.get('name', '')
            column_name = field.find('.//database/column-name')
            field_type = field.attrib.get('type', '')

            if column_name is not None and column_name.text and field_type:
                # Check if the field belongs to any of the specified tables
                belongs_to_table = any(
                    field_name in fields
                    for fields in table_fields.values()
                )
                if not belongs_to_table:
                    continue  # Skip fields not belonging to any table

                # Default to VARCHAR(100) if type is missing in type_mapping
                db_type = type_mapping.get(field_type, "VARCHAR(100)")
                if field_type not in type_mapping:
                    self.logger.warning(f"Missing type mapping for field: {field_name}, type: {field_type}. Defaulting to VARCHAR(100).")

                # Create a deep copy of the simulation config to avoid YAML anchors
                simulation = copy.deepcopy(simulation_config.get(db_type, {}))

                columns[column_name.text] = {
                    "type": db_type,
                    "field_name": field_name,
                    "simulation": simulation
                }

        # Write to YAML file (without YAML anchors)
        output_path = yaml_paths['columns']
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            yaml.dump({"columns": columns}, f, default_style=None, default_flow_style=False)

    def run(self):
        """
        Runs the configuration generation process.
        """
        self.generate_table_configs()
        self.generate_columns_config()

# Main execution
if __name__ == "__main__":
    config_generator = ConfigGenerator("data_simulator/config/config.yaml")
    config_generator.run()