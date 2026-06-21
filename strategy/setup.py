from setuptools import setup, find_packages

setup(
    name='quantboy',
    version='0.2.0',
    packages=find_packages(),
    install_requires=[
        'pandas>=1.5.0',
        'numpy>=1.23.0,<2.0.0',
        'matplotlib>=3.6.0',
        'requests>=2.28.0',
        'rqalpha==6.1.5',
    ],
    python_requires='>=3.8',
)
