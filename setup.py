from setuptools import setup

with open("README.md", "r") as fh:
    long_description = fh.read()

setup(
    name='prometheus-qbittorrent-exporter',
    packages=['qbittorrent_exporter'],
    version='1.1.0',
    long_description=long_description,
    long_description_content_type="text/markdown",
    description='Prometheus exporter for qbittorrent',
    author='Esteban Sanchez',
    author_email='esteban.sanchez@gmail.com',
    url='https://github.com/esanchezm/prometheus-qbittorrent-exporter',
    download_url='https://github.com/esanchezm/prometheus-qbittorrent-exporter/archive/1.1.0.tar.gz',
    keywords=['prometheus', 'qbittorrent'],
    classifiers=[],
    python_requires='>=3',
    install_requires=['qbittorrent-api==2021.4.20', 'prometheus_client==0.10.1', 'python-json-logger==2.0.1', 'attrdict'],
    entry_points={
        'console_scripts': [
            'qbittorrent-exporter=qbittorrent_exporter.exporter:main',
        ]
    }
)
