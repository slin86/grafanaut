import yaml
import os
from grafanaut.logger import setup_logger

logger = setup_logger(__name__)

class GrafanautConfig:
    def load_config(self, source, targets):
        logger.info("Loading configuration...")
        config = self.read_config()
        self.validate_config(config, source, targets)
        logger.info("done!")
        return config

    @staticmethod
    def get_token(config, stage):
        env_var = f"GRAFANA_TOKEN_{stage.upper()}"
        token = os.environ.get(env_var)

        if not token:
            token = config[stage]["token"]
        if not token:
            raise RuntimeError(f"Grafanaut: No token found in configuration {stage}")

        logger.debug(f"Found token for {stage}")

        return token

    def validate_config(self, config, source, targets):
        if source not in config:
            raise RuntimeError(f"Grafanaut: No configuration found for '{source}'")
        if targets is not None:
            for target in targets:
                if target not in config:
                    raise RuntimeError(f"Grafanaut: No configuration found for '{target}'")

    def read_config(self):
        with open("config.yaml") as f:
            config = yaml.safe_load(f)
        return config["instances"]