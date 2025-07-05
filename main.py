"""
Entry point for Alert Watcher 2 application.

This module provides the main entry point that delegates to the package's CLI.
"""

import sys
from src.alert_watcher.main import cli

if __name__ == "__main__":
    cli()
