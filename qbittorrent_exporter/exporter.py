import time
import os
import sys
import signal
import faulthandler
from attrdict import AttrDict
from qbittorrentapi import Client, TorrentStates
from prometheus_client import start_http_server
from prometheus_client.core import GaugeMetricFamily, CounterMetricFamily, REGISTRY
import logging
from pythonjsonlogger import jsonlogger


# Enable dumps on stderr in case of segfault
faulthandler.enable()
logger = logging.getLogger()

class QbittorrentMetricsCollector():
    TORRENT_STATUSES = [
        "downloading",
        "uploading",
        "complete",
        "checking",
        "errored",
        "paused",
    ]

    def __init__(self, config):
        self.config = config
        self.torrents = None
        self.client = Client(
            host=config["host"],
            port=config["port"],
            username=config["username"],
            password=config["password"],
        )

    def collect(self):
        try:
            self.torrents = self.client.torrents.info()
        except Exception as e:
            logger.error(f"Couldn't get server info: {e}")

        metrics = self.get_qbittorrent_metrics()

        for metric in metrics:
            name = metric["name"]
            value = metric["value"]
            help_text = metric.get("help", "")
            labels = metric.get("labels", {})
            metric_type = metric.get("type", "gauge")

            if metric_type == "counter":
                prom_metric = CounterMetricFamily(name, help_text, labels=labels.keys())
            else:
                prom_metric = GaugeMetricFamily(name, help_text, labels=labels.keys())
            prom_metric.add_metric(value=value, labels=labels.values())
            yield prom_metric

    def get_qbittorrent_metrics(self):
        metrics = []
        metrics.extend(self.get_qbittorrent_status_metrics())
        metrics.extend(self.get_qbittorrent_sync_main_metrics())
        metrics.extend(self.get_qbittorrent_torrent_tags_metrics())
        metrics.extend(self.get_qbittorrent_torrents_metrics())
        metrics.extend(self.get_qbittorrent_peers_metrics())

        return metrics

    def get_qbittorrent_status_metrics(self):
        # Fetch data from API
        try:
            response = self.client.transfer.info
            version = self.client.app.version
            self.torrents = self.client.torrents.info()
        except Exception as e:
            logger.error(f"Couldn't get server info: {e}")
            response = None
            version = ""

        return [
            {
                "name": f"{self.config['metrics_prefix']}_up",
                "value": response is not None,
                "labels": {"version": version},
                "help": "Whether if server is alive or not",
            },
            {
                "name": f"{self.config['metrics_prefix']}_connected",
                "value": response.get("connection_status", "") == "connected",
                "help": "Whether if server is connected or not",
            },
            {
                "name": f"{self.config['metrics_prefix']}_firewalled",
                "value": response.get("connection_status", "") == "firewalled",
                "help": "Whether if server is under a firewall or not",
            },
            {
                "name": f"{self.config['metrics_prefix']}_dht_nodes",
                "value": response.get("dht_nodes", 0),
                "help": "DHT nodes connected to",
            },
            {
                "name": f"{self.config['metrics_prefix']}_dl_info_data",
                "value": response.get("dl_info_data", 0),
                "help": "Data downloaded this session (bytes)",
                "type": "counter"
            },
            {
                "name": f"{self.config['metrics_prefix']}_up_info_data",
                "value": response.get("up_info_data", 0),
                "help": "Data uploaded this session (bytes)",
                "type": "counter"
            },
        ]
    
    def get_qbittorrent_sync_main_metrics(self):
        try:
            sync_main_response = self.client.sync_maindata()
        except Exception as e:
            logger.error(f"Couldn't fetch sync maindata: {e}")
            return []
        
        if not sync_main_response:
            return []

        server_state = sync_main_response["server_state"]
        if not server_state:
            return []

        return [
            {
                "name": f"{self.config['metrics_prefix']}_average_time_queue",
                "value": server_state["average_time_queue"],
                "help": "Average disk job time in ms",
                "type": "gauge"
            },
            {
                "name": f"{self.config['metrics_prefix']}_read_cache_hits",
                "value": server_state["read_cache_hits"],
                "help": "Read cache hits in percent",
                "type": "gauge"
            },
            {
                "name": f"{self.config['metrics_prefix']}_total_buffers_size",
                "value": server_state["total_buffers_size"],
                "help": "Total buffer size in bytes",
                "type": "gauge"
            },
            {
                "name": f"{self.config['metrics_prefix']}_total_peer_connections",
                "value": server_state["total_peer_connections"],
                "help": "Total peer connections",
                "type": "gauge"
            },
            {
                "name": f"{self.config['metrics_prefix']}_total_wasted",
                "value": server_state["total_wasted_session"],
                "help": "Total wasted in bytes",
                "type": "counter"
            },
            {
                "name": f"{self.config['metrics_prefix']}_write_cache_overload",
                "value": server_state["write_cache_overload"],
                "help": "Write cache overload in percent",
                "type": "gauge"
            },
        ]


    def get_qbittorrent_torrent_tags_metrics(self):
        try:
            categories = self.client.torrent_categories.categories
        except Exception as e:
            logger.error(f"Couldn't fetch categories: {e}")
            return []

        if not self.torrents:
            return []

        metrics = []
        categories.Uncategorized = AttrDict({'name': 'Uncategorized', 'savePath': ''})
        for category in categories:
            category_torrents = [t for t in self.torrents if t['category'] == category or (category == "Uncategorized" and t['category'] == "")]

            for status in self.TORRENT_STATUSES:
                status_prop = f"is_{status}"
                status_torrents = [
                    t for t in category_torrents if getattr(TorrentStates, status_prop).fget(TorrentStates(t['state']))
                ]
                metrics.append({
                    "name": f"{self.config['metrics_prefix']}_torrents_count",
                    "value": len(status_torrents),
                    "labels": {
                        "status": status,
                        "category": category,
                    },
                    "help": f"Number of torrents in status {status} under category {category}"
                })

        return metrics

    def get_qbittorrent_torrents_metrics(self):
        if not self.torrents:
            return []

        metrics = []
        for torrent in self.torrents:
            metrics.extend([
                {
                    "name": f"{self.config['metrics_prefix']}_torrents_info_added_on",
                    "value": torrent["added_on"],
                    "labels": {
                        "name": torrent["name"],
                        "category": torrent["category"],
                        "hash": torrent["hash"]
                    },
                    "help": f"Time (Unix Epoch) when the torrent was added to the client",
                    "type": "gauge"
                },
                {
                    "name": f"{self.config['metrics_prefix']}_torrents_info_availability",
                    "value": torrent["availability"],
                    "labels": {
                        "name": torrent["name"],
                        "category": torrent["category"],
                        "hash": torrent["hash"]
                    },
                    "help": f"Percentage of file pieces currently available",
                    "type": "gauge"
                },
                {
                    "name": f"{self.config['metrics_prefix']}_torrents_info_downloaded",
                    "value": torrent["downloaded"],
                    "labels": {
                        "name": torrent["name"],
                        "category": torrent["category"],
                        "hash": torrent["hash"]
                    },
                    "help": f"Amount of data downloaded",
                    "type": "counter"
                },
                {
                    "name": f"{self.config['metrics_prefix']}_torrents_info_num_complete",
                    "value": torrent["num_complete"],
                    "labels": {
                        "name": torrent["name"],
                        "category": torrent["category"],
                        "hash": torrent["hash"]
                    },
                    "help": f"Number of seeds in the swarm",
                    "type": "gauge"
                },
                {
                    "name": f"{self.config['metrics_prefix']}_torrents_info_num_incomplete",
                    "value": torrent["num_incomplete"],
                    "labels": {
                        "name": torrent["name"],
                        "category": torrent["category"],
                        "hash": torrent["hash"]
                    },
                    "help": f"Number of leechers in the swarm",
                    "type": "gauge"
                },
                {
                    "name": f"{self.config['metrics_prefix']}_torrents_info_num_leechs",
                    "value": torrent["num_leechs"],
                    "labels": {
                        "name": torrent["name"],
                        "category": torrent["category"],
                        "hash": torrent["hash"]
                    },
                    "help": f"Number of leechers connected to",
                    "type": "gauge"
                },
                {
                    "name": f"{self.config['metrics_prefix']}_torrents_info_num_seeds",
                    "value": torrent["num_seeds"],
                    "labels": {
                        "name": torrent["name"],
                        "category": torrent["category"],
                        "hash": torrent["hash"]
                    },
                    "help": f"Number of seeds connected to",
                    "type": "gauge"
                },
                {
                    "name": f"{self.config['metrics_prefix']}_torrents_info_ratio",
                    "value": torrent["ratio"],
                    "labels": {
                        "name": torrent["name"],
                        "category": torrent["category"],
                        "hash": torrent["hash"]
                    },
                    "help": f"Torrent share ratio. Max ratio value: 9999.",
                    "type": "gauge"
                },
                {
                    "name": f"{self.config['metrics_prefix']}_torrents_seeding_time",
                    "value": torrent["seeding_time"],
                    "labels": {
                        "name": torrent["name"],
                        "category": torrent["category"],
                        "hash": torrent["hash"]
                    },
                    "help": f"Torrent elapsed time while complete (seconds)",
                    "type": "gauge"
                },
                {
                    "name": f"{self.config['metrics_prefix']}_torrents_info_size",
                    "value": torrent["size"],
                    "labels": {
                        "name": torrent["name"],
                        "category": torrent["category"],
                        "hash": torrent["hash"]
                    },
                    "help": f"Total size (bytes) of files selected for download",
                    "type": "gauge"
                },
                {
                    "name": f"{self.config['metrics_prefix']}_torrents_info_total_size",
                    "value": torrent["total_size"],
                    "labels": {
                        "name": torrent["name"],
                        "category": torrent["category"],
                        "hash": torrent["hash"]
                    },
                    "help": f"Total size (bytes) of all file in this torrent (including unselected ones)",
                    "type": "gauge"
                },
                {
                    "name": f"{self.config['metrics_prefix']}_torrents_info_time_active",
                    "value": torrent["time_active"],
                    "labels": {
                        "name": torrent["name"],
                        "category": torrent["category"],
                        "hash": torrent["hash"]
                    },
                    "help": f"Total active time (seconds)",
                    "type": "gauge"
                },
                {
                    "name": f"{self.config['metrics_prefix']}_torrents_info_uploaded",
                    "value": torrent["uploaded"],
                    "labels": {
                        "name": torrent["name"],
                        "category": torrent["category"],
                        "hash": torrent["hash"]
                    },
                    "help": f"Amount of data uploaded",
                    "type": "counter"
                },
            ])

        return metrics

    def get_qbittorrent_peers_metrics(self):
        if not self.torrents:
            return []

        metrics = []
        for torrent in self.torrents:
            try:
                torrent_peers = self.client.sync_torrent_peers(torrent_hash=torrent["hash"])
            except Exception as e:
                logger.error(f"Couldn't fetch torrent peers ({torrent['hash']}): {e}")
                continue

            peers = torrent_peers["peers"]
            if not peers:
                continue

            for peer in peers.values():
                metrics.extend([
                    {
                        "name": f"{self.config['metrics_prefix']}_peers_downloaded",
                        "value": peer["downloaded"],
                        "labels": {
                            "torrent_name": torrent["name"],
                            "torrent_hash": torrent["hash"],
                            "country": peer["country"],
                            "country_code": peer["country_code"],
                            "ip": peer["ip"],
                            "port": str(peer["port"])
                        },
                        "help": f"Amount of data downloaded by peer",
                        "type": "counter"
                    },
                    {
                        "name": f"{self.config['metrics_prefix']}_peers_uploaded",
                        "value": peer["uploaded"],
                        "labels": {
                            "torrent_name": torrent["name"],
                            "torrent_hash": torrent["hash"],
                            "country": peer["country"],
                            "country_code": peer["country_code"],
                            "ip": peer["ip"],
                            "port": str(peer["port"])
                        },
                        "help": f"Amount of data uploaded by peer",
                        "type": "counter"
                    },
                    {
                        "name": f"{self.config['metrics_prefix']}_peers_progress",
                        "value": peer["progress"],
                        "labels": {
                            "torrent_name": torrent["name"],
                            "torrent_hash": torrent["hash"],
                            "country": peer["country"],
                            "country_code": peer["country_code"],
                            "ip": peer["ip"],
                            "port": str(peer["port"])
                        },
                        "type": "gauge"
                    },
                    {
                        "name": f"{self.config['metrics_prefix']}_peers_relevance",
                        "value": peer["relevance"],
                        "labels": {
                            "torrent_name": torrent["name"],
                            "torrent_hash": torrent["hash"],
                            "country": peer["country"],
                            "country_code": peer["country_code"],
                            "ip": peer["ip"],
                            "port": str(peer["port"])
                        },
                        "type": "gauge"
                    },
            ])

        return metrics

class SignalHandler():
    def __init__(self):
        self.shutdown = False

        # Register signal handler
        signal.signal(signal.SIGINT, self._on_signal_received)
        signal.signal(signal.SIGTERM, self._on_signal_received)

    def is_shutting_down(self):
        return self.shutdown

    def _on_signal_received(self, signal, frame):
        logger.info("Exporter is shutting down")
        self.shutdown = True


def main():
    config = {
        "host": os.environ.get("QBITTORRENT_HOST", ""),
        "port": os.environ.get("QBITTORRENT_PORT", ""),
        "username": os.environ.get("QBITTORRENT_USER", ""),
        "password": os.environ.get("QBITTORRENT_PASS", ""),
        "exporter_port": int(os.environ.get("EXPORTER_PORT", "8000")),
        "log_level": os.environ.get("EXPORTER_LOG_LEVEL", "INFO"),
        "metrics_prefix": os.environ.get("METRICS_PREFIX", "qbittorrent"),
    }

    # Register signal handler
    signal_handler = SignalHandler()

    # Init logger
    logHandler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter(
        "%(asctime) %(levelname) %(message)",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    logHandler.setFormatter(formatter)
    logger = logging.getLogger()
    logger.addHandler(logHandler)
    logger.setLevel(config["log_level"])

    if not config["host"]:
        logger.error("No host specified, please set QBITTORRENT_HOST environment variable")
        sys.exit(1)
    if not config["port"]:
        logger.error("No post specified, please set QBITTORRENT_PORT environment variable")
        sys.exit(1)

    # Register our custom collector
    logger.info("Exporter is starting up")
    REGISTRY.register(QbittorrentMetricsCollector(config))

    # Start server
    start_http_server(config["exporter_port"])
    logger.info(
        f"Exporter listening on port {config['exporter_port']}"
    )

    while not signal_handler.is_shutting_down():
        time.sleep(1)

    logger.info("Exporter has shutdown")
