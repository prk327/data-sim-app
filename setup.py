from setuptools import setup, find_packages

setup(
    name='data_simulator',
    version='0.1.0',
    author='Prabhakar Srivastav',
    author_email='prabhakar.srivastav@radcom.com',
    description='A package for data simulation and Vertica DB operations',
    packages=find_packages(),
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
