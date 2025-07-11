"""
Alert Buffer Storage implementation for persistent storage of alerts.

This module provides file-based storage for buffered alerts, ensuring alerts
are not lost when the webhook server or agent restarts.
"""

import json
import os
import fcntl
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set
import logging
from contextlib import contextmanager
import threading

from .models import BufferedAlert, AlertBufferConfig, AlertBufferStats, AlertBufferStatus


logger = logging.getLogger(__name__)


class AlertBufferStorage:
    """File-based storage for buffered alerts with thread-safe operations."""
    
    def __init__(self, config: AlertBufferConfig):
        """Initialize storage with configuration."""
        self.config = config
        self.storage_path = Path(config.storage_path)
        self.lock = threading.RLock()
        
        # Create storage directory if it doesn't exist
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        # File paths
        self.alerts_file = self.storage_path / "alerts.json"
        self.index_file = self.storage_path / "index.json"
        self.stats_file = self.storage_path / "stats.json"
        self.lock_file = self.storage_path / "storage.lock"
        
        logger.info(f"AlertBufferStorage initialized with path: {self.storage_path}")
    
    @contextmanager
    def _file_lock(self, file_path: Path):
        """Context manager for file locking."""
        lock_fd = None
        try:
            lock_fd = os.open(str(file_path), os.O_CREAT | os.O_WRONLY, 0o644)
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            yield
        finally:
            if lock_fd is not None:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                os.close(lock_fd)
    
    def _load_alerts(self) -> Dict[str, BufferedAlert]:
        """Load all alerts from storage."""
        if not self.alerts_file.exists():
            return {}
        
        try:
            with open(self.alerts_file, 'r') as f:
                data = json.load(f)
            
            alerts = {}
            for alert_id, alert_data in data.items():
                try:
                    alerts[alert_id] = BufferedAlert.from_dict(alert_data)
                except Exception as e:
                    logger.error(f"Failed to deserialize alert {alert_id}: {e}")
                    continue
            
            return alerts
            
        except Exception as e:
            logger.error(f"Failed to load alerts from storage: {e}")
            return {}
    
    def _save_alerts(self, alerts: Dict[str, BufferedAlert]):
        """Save all alerts to storage."""
        try:
            data = {}
            for alert_id, alert in alerts.items():
                data[alert_id] = alert.to_dict()
            
            # Write to temporary file first, then rename for atomic operation
            temp_file = self.alerts_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            # Atomic rename
            temp_file.replace(self.alerts_file)
            
        except Exception as e:
            logger.error(f"Failed to save alerts to storage: {e}")
            raise
    
    def _load_index(self) -> Dict[str, Set[str]]:
        """Load alert index for efficient querying."""
        if not self.index_file.exists():
            return {
                'by_status': {},
                'by_cluster': {},
                'by_namespace': {},
                'by_alert_name': {}
            }
        
        try:
            with open(self.index_file, 'r') as f:
                data = json.load(f)
            
            # Convert lists back to sets
            index = {}
            for category, subcategories in data.items():
                index[category] = {}
                for key, alert_ids in subcategories.items():
                    index[category][key] = set(alert_ids)
            
            return index
            
        except Exception as e:
            logger.error(f"Failed to load index from storage: {e}")
            return {
                'by_status': {},
                'by_cluster': {},
                'by_namespace': {},
                'by_alert_name': {}
            }
    
    def _save_index(self, index: Dict[str, Set[str]]):
        """Save alert index to storage."""
        try:
            # Convert sets to lists for JSON serialization
            data = {}
            for category, subcategories in index.items():
                data[category] = {}
                for key, alert_ids in subcategories.items():
                    data[category][key] = list(alert_ids)
            
            temp_file = self.index_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            temp_file.replace(self.index_file)
            
        except Exception as e:
            logger.error(f"Failed to save index to storage: {e}")
    
    def _update_index(self, alerts: Dict[str, BufferedAlert]) -> Dict[str, Set[str]]:
        """Update index based on current alerts."""
        index = {
            'by_status': {},
            'by_cluster': {},
            'by_namespace': {},
            'by_alert_name': {}
        }
        
        for alert_id, alert in alerts.items():
            # Index by status
            status_key = alert.status.value
            if status_key not in index['by_status']:
                index['by_status'][status_key] = set()
            index['by_status'][status_key].add(alert_id)
            
            # Index by cluster
            cluster_key = alert.cluster_context
            if cluster_key not in index['by_cluster']:
                index['by_cluster'][cluster_key] = set()
            index['by_cluster'][cluster_key].add(alert_id)
            
            # Index by namespace
            namespace_key = alert.namespace
            if namespace_key not in index['by_namespace']:
                index['by_namespace'][namespace_key] = set()
            index['by_namespace'][namespace_key].add(alert_id)
            
            # Index by alert name
            alert_name_key = alert.alert_name
            if alert_name_key not in index['by_alert_name']:
                index['by_alert_name'][alert_name_key] = set()
            index['by_alert_name'][alert_name_key].add(alert_id)
        
        return index
    
    def store_alert(self, alert: BufferedAlert) -> bool:
        """Store a single alert."""
        with self.lock:
            with self._file_lock(self.lock_file):
                try:
                    alerts = self._load_alerts()
                    
                    # Check if we're at capacity
                    if len(alerts) >= self.config.max_buffer_size:
                        # Remove oldest processed or expired alert
                        oldest_alert_id = self._find_oldest_removable_alert(alerts)
                        if oldest_alert_id:
                            del alerts[oldest_alert_id]
                            logger.info(f"Removed oldest alert {oldest_alert_id} to make space")
                        else:
                            logger.error("Buffer is full and no alerts can be removed")
                            return False
                    
                    # Store the alert
                    alerts[alert.buffer_id] = alert
                    self._save_alerts(alerts)
                    
                    # Update index
                    index = self._update_index(alerts)
                    self._save_index(index)
                    
                    logger.info(f"Stored alert {alert.buffer_id} ({alert.alert_name})")
                    return True
                    
                except Exception as e:
                    logger.error(f"Failed to store alert {alert.buffer_id}: {e}")
                    return False
    
    def get_alert(self, buffer_id: str) -> Optional[BufferedAlert]:
        """Get a specific alert by buffer ID."""
        with self.lock:
            try:
                alerts = self._load_alerts()
                return alerts.get(buffer_id)
            except Exception as e:
                logger.error(f"Failed to get alert {buffer_id}: {e}")
                return None
    
    def get_alerts_by_status(self, status: AlertBufferStatus) -> List[BufferedAlert]:
        """Get all alerts with a specific status."""
        with self.lock:
            try:
                alerts = self._load_alerts()
                return [alert for alert in alerts.values() if alert.status == status]
            except Exception as e:
                logger.error(f"Failed to get alerts by status {status}: {e}")
                return []
    
    def get_buffered_alerts(self) -> List[BufferedAlert]:
        """Get all buffered alerts ready for processing."""
        return self.get_alerts_by_status(AlertBufferStatus.BUFFERED)
    
    def get_failed_alerts(self) -> List[BufferedAlert]:
        """Get all failed alerts that can be retried."""
        with self.lock:
            try:
                alerts = self._load_alerts()
                return [
                    alert for alert in alerts.values() 
                    if alert.status == AlertBufferStatus.FAILED and alert.can_retry
                ]
            except Exception as e:
                logger.error(f"Failed to get failed alerts: {e}")
                return []
    
    def update_alert_status(self, buffer_id: str, status: AlertBufferStatus, error_message: Optional[str] = None) -> bool:
        """Update the status of an alert."""
        with self.lock:
            with self._file_lock(self.lock_file):
                try:
                    alerts = self._load_alerts()
                    
                    if buffer_id not in alerts:
                        logger.error(f"Alert {buffer_id} not found")
                        return False
                    
                    alert = alerts[buffer_id]
                    
                    if status == AlertBufferStatus.PROCESSING:
                        alert.mark_processing()
                    elif status == AlertBufferStatus.PROCESSED:
                        alert.mark_processed()
                    elif status == AlertBufferStatus.FAILED:
                        alert.mark_failed(error_message or "Unknown error")
                    elif status == AlertBufferStatus.EXPIRED:
                        alert.mark_expired()
                    else:
                        alert.status = status
                    
                    self._save_alerts(alerts)
                    
                    # Update index
                    index = self._update_index(alerts)
                    self._save_index(index)
                    
                    logger.info(f"Updated alert {buffer_id} status to {status.value}")
                    return True
                    
                except Exception as e:
                    logger.error(f"Failed to update alert {buffer_id} status: {e}")
                    return False
    
    def remove_alert(self, buffer_id: str) -> bool:
        """Remove an alert from storage."""
        with self.lock:
            with self._file_lock(self.lock_file):
                try:
                    alerts = self._load_alerts()
                    
                    if buffer_id not in alerts:
                        logger.warning(f"Alert {buffer_id} not found for removal")
                        return False
                    
                    del alerts[buffer_id]
                    self._save_alerts(alerts)
                    
                    # Update index
                    index = self._update_index(alerts)
                    self._save_index(index)
                    
                    logger.info(f"Removed alert {buffer_id}")
                    return True
                    
                except Exception as e:
                    logger.error(f"Failed to remove alert {buffer_id}: {e}")
                    return False
    
    def cleanup_expired_alerts(self) -> int:
        """Remove expired alerts from storage."""
        with self.lock:
            with self._file_lock(self.lock_file):
                try:
                    alerts = self._load_alerts()
                    removed_count = 0
                    
                    expired_alerts = []
                    for alert_id, alert in alerts.items():
                        if alert.is_expired:
                            expired_alerts.append(alert_id)
                    
                    for alert_id in expired_alerts:
                        del alerts[alert_id]
                        removed_count += 1
                    
                    if removed_count > 0:
                        self._save_alerts(alerts)
                        
                        # Update index
                        index = self._update_index(alerts)
                        self._save_index(index)
                        
                        logger.info(f"Cleaned up {removed_count} expired alerts")
                    
                    return removed_count
                    
                except Exception as e:
                    logger.error(f"Failed to cleanup expired alerts: {e}")
                    return 0
    
    def cleanup_processed_alerts(self) -> int:
        """Remove old processed alerts from storage."""
        with self.lock:
            with self._file_lock(self.lock_file):
                try:
                    alerts = self._load_alerts()
                    removed_count = 0
                    
                    cutoff_time = datetime.now() - timedelta(hours=self.config.keep_processed_alerts_hours)
                    
                    processed_alerts = []
                    for alert_id, alert in alerts.items():
                        if (alert.status == AlertBufferStatus.PROCESSED and 
                            alert.processed_at and 
                            alert.processed_at < cutoff_time):
                            processed_alerts.append(alert_id)
                    
                    for alert_id in processed_alerts:
                        del alerts[alert_id]
                        removed_count += 1
                    
                    if removed_count > 0:
                        self._save_alerts(alerts)
                        
                        # Update index
                        index = self._update_index(alerts)
                        self._save_index(index)
                        
                        logger.info(f"Cleaned up {removed_count} old processed alerts")
                    
                    return removed_count
                    
                except Exception as e:
                    logger.error(f"Failed to cleanup processed alerts: {e}")
                    return 0
    
    def get_stats(self) -> AlertBufferStats:
        """Get storage statistics."""
        with self.lock:
            try:
                alerts = self._load_alerts()
                
                stats = AlertBufferStats()
                stats.total_alerts = len(alerts)
                
                # Count by status
                for alert in alerts.values():
                    if alert.status == AlertBufferStatus.BUFFERED:
                        stats.buffered_alerts += 1
                    elif alert.status == AlertBufferStatus.PROCESSING:
                        stats.processing_alerts += 1
                    elif alert.status == AlertBufferStatus.PROCESSED:
                        stats.processed_alerts += 1
                    elif alert.status == AlertBufferStatus.FAILED:
                        stats.failed_alerts += 1
                    elif alert.status == AlertBufferStatus.EXPIRED:
                        stats.expired_alerts += 1
                
                # Calculate age statistics
                if alerts:
                    ages = [alert.age for alert in alerts.values()]
                    stats.oldest_alert_age = max(ages)
                    stats.newest_alert_age = min(ages)
                
                # Calculate retry statistics
                stats.total_retries = sum(alert.retry_count for alert in alerts.values())
                
                # Calculate success rate
                if stats.total_alerts > 0:
                    stats.success_rate = stats.processed_alerts / stats.total_alerts
                
                return stats
                
            except Exception as e:
                logger.error(f"Failed to get storage stats: {e}")
                return AlertBufferStats()
    
    def _find_oldest_removable_alert(self, alerts: Dict[str, BufferedAlert]) -> Optional[str]:
        """Find the oldest alert that can be removed (processed or expired)."""
        removable_alerts = []
        
        for alert_id, alert in alerts.items():
            if alert.status in [AlertBufferStatus.PROCESSED, AlertBufferStatus.EXPIRED]:
                removable_alerts.append((alert_id, alert.buffered_at))
        
        if not removable_alerts:
            return None
        
        # Return the oldest removable alert
        oldest_alert = min(removable_alerts, key=lambda x: x[1])
        return oldest_alert[0]
    
    def get_all_alerts(self) -> List[BufferedAlert]:
        """Get all alerts from storage."""
        with self.lock:
            try:
                alerts = self._load_alerts()
                return list(alerts.values())
            except Exception as e:
                logger.error(f"Failed to get all alerts: {e}")
                return []
    
    def clear_all_alerts(self) -> bool:
        """Clear all alerts from storage (for testing)."""
        with self.lock:
            with self._file_lock(self.lock_file):
                try:
                    # Remove all files
                    for file_path in [self.alerts_file, self.index_file, self.stats_file]:
                        if file_path.exists():
                            file_path.unlink()
                    
                    logger.info("Cleared all alerts from storage")
                    return True
                    
                except Exception as e:
                    logger.error(f"Failed to clear alerts: {e}")
                    return False