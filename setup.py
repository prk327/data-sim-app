from setuptools import setup, find_packages
from setuptools.command.develop import develop
import os
from pathlib import Path

class PostDevelopCommand(develop):
    """Post-installation for development mode (creates symlinks)."""
    def run(self):
        # Run original install
        develop.run(self)
        
        # Create symlinks for development
        package_dir = Path(__file__).parent / "data_simulator"
        os.symlink(
            "../../config",
            package_dir / "config",
            target_is_directory=True
        )
        os.symlink(
            "../../sql",
            package_dir / "sql",
            target_is_directory=True
        )
        print("Created symlinks for config/ and sql/ directories")

setup(
    name='data_simulator',
    version='0.1.0',
    author='Prabhakar Srivastav',
    author_email='prabhakar.srivastav@radcom.com',
    description='A package for data simulation and Vertica DB operations',
    packages=find_packages(),
    package_data={
        'data_simulator': [
            'config/*.yaml',
            'sql/*.yaml',
            'config/columns/*.yaml',
            'config/tables/*.yaml'
        ],
    },
    include_package_data=True,
    install_requires=[
        'faker',
        'vertica-python',
        'PyYAML',
        'Jinja2',
        'tqdm'
    ],
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License'
    ],
)
