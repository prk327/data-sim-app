from pathlib import Path

def get_config_path(config_file):
    """Get path to config file"""
    package_dir = Path(__file__).parent
    return str(package_dir / "config" / config_file)