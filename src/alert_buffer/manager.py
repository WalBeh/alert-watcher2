"""
Alert Buffer Manager for high-level alert buffering operations.

This module provides a high-level interface for managing buffered alerts,
including automatic flushing, retry logic, and background cleanup tasks.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from .models import BufferedAlert, AlertBufferConfig, AlertBufferStats, AlertBufferStatus, AlertBufferOperation
from .storage import AlertBufferStorage

logger = logging.getLogger(__name__)


class AlertBufferManager:
    """High-level manager for alert buffering operations."""
    
    def __init__(self, config: AlertBufferConfig, agent_check_callback: Optional[Callable[[], bool]] = None):
        """
        Initialize the alert buffer manager.
        
        Args:
            config: Buffer configuration
            agent_check_callback: Function to check if the agent is available
        """
        self.config = config
        self.storage = AlertBufferStorage(config)
        self.agent_check_callback = agent_check_callback
        
        # Background task management
        self._running = False
        self._flush_task = None
        self._cleanup_task = None
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="alert-buffer")
        
        # Statistics
        self._last_flush_at = None
        self._last_cleanup_at = None
        self._flush_count = 0
        self._cleanup_count = 0
        
        # Alert processing callback
        self._alert_processor = None
        
        logger.info("AlertBufferManager initialized")
    
    def set_alert_processor(self, processor: Callable[[BufferedAlert], bool]):
        """Set the function to process buffered alerts."""
        self._alert_processor = processor
        logger.info("Alert processor callback set")
    
    def is_agent_available(self) -> bool:
        """Check if the agent is available for processing alerts."""
        if self.agent_check_callback:
            try:
                return self.agent_check_callback()
            except Exception as e:
                logger.error(f"Agent availability check failed: {e}")
                return False
        return True
    
    def buffer_alert(self, alert_data: Dict[str, Any]) -> AlertBufferOperation:
        """
        Buffer an alert for later processing.
        
        Args:
            alert_data: Alert command data from webhook
            
        Returns:
            AlertBufferOperation result
        """
        try:
            # Create buffered alert
            buffered_alert = BufferedAlert.from_webhook_data(alert_data)
            
            # Store in buffer
            success = self.storage.store_alert(buffered_alert)
            
            if success:
                logger.info(
                    f"Buffered alert {buffered_alert.alert_name} for {buffered_alert.namespace}/{buffered_alert.pod}",
                    extra={
                        'buffer_id': buffered_alert.buffer_id,
                        'alert_name': buffered_alert.alert_name,
                        'namespace': buffered_alert.namespace,
                        'pod': buffered_alert.pod,
                        'cluster_context': buffered_alert.cluster_context,
                        'region': buffered_alert.region
                    }
                )
                
                return AlertBufferOperation(
                    success=True,
                    operation="buffer_alert",
                    alert_id=buffered_alert.buffer_id,
                    message=f"Alert buffered successfully: {buffered_alert.alert_name}"
                )
            else:
                return AlertBufferOperation(
                    success=False,
                    operation="buffer_alert",
                    alert_id=buffered_alert.buffer_id,
                    error="Failed to store alert in buffer"
                )
                
        except Exception as e:
            logger.error(f"Failed to buffer alert: {e}", exc_info=True)
            return AlertBufferOperation(
                success=False,
                operation="buffer_alert",
                error=str(e)
            )
    
    def process_buffered_alerts(self) -> List[AlertBufferOperation]:
        """
        Process all buffered alerts that are ready for processing.
        
        Returns:
            List of processing results
        """
        results = []
        
        if not self._alert_processor:
            logger.warning("No alert processor set, cannot process buffered alerts")
            return results
        
        try:
            # Get buffered alerts
            buffered_alerts = self.storage.get_buffered_alerts()
            
            # Also get failed alerts that can be retried
            failed_alerts = self.storage.get_failed_alerts()
            
            all_alerts = buffered_alerts + failed_alerts
            
            if not all_alerts:
                return results
            
            logger.info(f"Processing {len(all_alerts)} buffered alerts")
            
            for alert in all_alerts:
                result = self._process_single_alert(alert)
                results.append(result)
                
                # Add small delay between processing alerts
                time.sleep(0.1)
            
            return results
            
        except Exception as e:
            logger.error(f"Failed to process buffered alerts: {e}", exc_info=True)
            return results
    
    def _process_single_alert(self, alert: BufferedAlert) -> AlertBufferOperation:
        """Process a single buffered alert."""
        try:
            # Mark as processing
            self.storage.update_alert_status(alert.buffer_id, AlertBufferStatus.PROCESSING)
            
            # Convert to command data
            command_data = alert.to_command_data()
            
            logger.info(
                f"Processing buffered alert {alert.alert_name}",
                extra={
                    'buffer_id': alert.buffer_id,
                    'alert_name': alert.alert_name,
                    'namespace': alert.namespace,
                    'pod': alert.pod,
                    'retry_count': alert.retry_count
                }
            )
            
            # Process the alert
            success = self._alert_processor(alert)
            
            if success:
                # Mark as processed
                self.storage.update_alert_status(alert.buffer_id, AlertBufferStatus.PROCESSED)
                
                logger.info(
                    f"Successfully processed buffered alert {alert.alert_name}",
                    extra={'buffer_id': alert.buffer_id}
                )
                
                return AlertBufferOperation(
                    success=True,
                    operation="process_alert",
                    alert_id=alert.buffer_id,
                    message=f"Alert processed successfully: {alert.alert_name}"
                )
            else:
                # Mark as failed
                error_msg = f"Alert processor returned failure for {alert.alert_name}"
                self.storage.update_alert_status(alert.buffer_id, AlertBufferStatus.FAILED, error_msg)
                
                logger.error(
                    f"Failed to process buffered alert {alert.alert_name}",
                    extra={'buffer_id': alert.buffer_id}
                )
                
                return AlertBufferOperation(
                    success=False,
                    operation="process_alert",
                    alert_id=alert.buffer_id,
                    error=error_msg
                )
                
        except Exception as e:
            error_msg = f"Exception processing alert {alert.alert_name}: {str(e)}"
            self.storage.update_alert_status(alert.buffer_id, AlertBufferStatus.FAILED, error_msg)
            
            logger.error(
                f"Exception processing buffered alert {alert.alert_name}: {e}",
                extra={'buffer_id': alert.buffer_id},
                exc_info=True
            )
            
            return AlertBufferOperation(
                success=False,
                operation="process_alert",
                alert_id=alert.buffer_id,
                error=error_msg
            )
    
    def flush_buffer(self) -> AlertBufferOperation:
        """
        Flush buffered alerts if the agent is available.
        
        Returns:
            AlertBufferOperation result
        """
        try:
            if not self.is_agent_available():
                return AlertBufferOperation(
                    success=False,
                    operation="flush_buffer",
                    message="Agent not available, alerts remain buffered"
                )
            
            # Process buffered alerts
            results = self.process_buffered_alerts()
            
            success_count = sum(1 for r in results if r.success)
            error_count = len(results) - success_count
            
            self._last_flush_at = datetime.now()
            self._flush_count += 1
            
            if results:
                logger.info(f"Flushed {success_count} alerts successfully, {error_count} failed")
            
            return AlertBufferOperation(
                success=True,
                operation="flush_buffer",
                message=f"Processed {success_count} alerts, {error_count} failed"
            )
            
        except Exception as e:
            logger.error(f"Failed to flush buffer: {e}", exc_info=True)
            return AlertBufferOperation(
                success=False,
                operation="flush_buffer",
                error=str(e)
            )
    
    def cleanup_buffer(self) -> AlertBufferOperation:
        """
        Clean up expired and old processed alerts.
        
        Returns:
            AlertBufferOperation result
        """
        try:
            expired_count = 0
            processed_count = 0
            
            if self.config.cleanup_expired_alerts:
                expired_count = self.storage.cleanup_expired_alerts()
            
            if self.config.cleanup_processed_alerts:
                processed_count = self.storage.cleanup_processed_alerts()
            
            total_cleaned = expired_count + processed_count
            
            self._last_cleanup_at = datetime.now()
            self._cleanup_count += 1
            
            if total_cleaned > 0:
                logger.info(f"Cleaned up {expired_count} expired and {processed_count} processed alerts")
            
            return AlertBufferOperation(
                success=True,
                operation="cleanup_buffer",
                message=f"Cleaned up {total_cleaned} alerts ({expired_count} expired, {processed_count} processed)"
            )
            
        except Exception as e:
            logger.error(f"Failed to cleanup buffer: {e}", exc_info=True)
            return AlertBufferOperation(
                success=False,
                operation="cleanup_buffer",
                error=str(e)
            )
    
    def get_buffer_stats(self) -> AlertBufferStats:
        """Get comprehensive buffer statistics."""
        try:
            stats = self.storage.get_stats()
            
            # Add manager-specific stats
            stats.last_flush_at = self._last_flush_at
            stats.last_cleanup_at = self._last_cleanup_at
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get buffer stats: {e}", exc_info=True)
            return AlertBufferStats()
    
    def get_alert_by_id(self, buffer_id: str) -> Optional[BufferedAlert]:
        """Get a specific buffered alert by ID."""
        return self.storage.get_alert(buffer_id)
    
    def get_all_alerts(self) -> List[BufferedAlert]:
        """Get all buffered alerts."""
        return self.storage.get_all_alerts()
    
    def start_background_tasks(self):
        """Start background tasks for automatic buffer management."""
        if self._running:
            logger.warning("Background tasks already running")
            return
        
        self._running = True
        
        # Start flush task
        self._flush_task = asyncio.create_task(self._flush_task_worker())
        
        # Start cleanup task
        self._cleanup_task = asyncio.create_task(self._cleanup_task_worker())
        
        logger.info("Started background tasks for buffer management")
    
    def stop_background_tasks(self):
        """Stop background tasks."""
        if not self._running:
            return
        
        self._running = False
        
        # Cancel tasks
        if self._flush_task:
            self._flush_task.cancel()
        
        if self._cleanup_task:
            self._cleanup_task.cancel()
        
        logger.info("Stopped background tasks for buffer management")
    
    async def _flush_task_worker(self):
        """Background task worker for flushing alerts."""
        while self._running:
            try:
                # Run flush in executor to avoid blocking
                await asyncio.get_event_loop().run_in_executor(
                    self._executor, self.flush_buffer
                )
                
                # Wait for next flush interval
                await asyncio.sleep(self.config.flush_interval_seconds)
                
            except asyncio.CancelledError:
                logger.info("Flush task cancelled")
                break
            except Exception as e:
                logger.error(f"Error in flush task worker: {e}", exc_info=True)
                await asyncio.sleep(self.config.flush_interval_seconds)
    
    async def _cleanup_task_worker(self):
        """Background task worker for cleanup."""
        while self._running:
            try:
                # Wait for cleanup interval
                await asyncio.sleep(self.config.cleanup_interval_minutes * 60)
                
                # Run cleanup in executor to avoid blocking
                await asyncio.get_event_loop().run_in_executor(
                    self._executor, self.cleanup_buffer
                )
                
            except asyncio.CancelledError:
                logger.info("Cleanup task cancelled")
                break
            except Exception as e:
                logger.error(f"Error in cleanup task worker: {e}", exc_info=True)
                await asyncio.sleep(60)  # Wait 1 minute before retry
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop_background_tasks()
        self._executor.shutdown(wait=True)
    
    @asynccontextmanager
    async def managed_lifecycle(self):
        """Async context manager for managing the buffer lifecycle."""
        try:
            self.start_background_tasks()
            yield self
        finally:
            self.stop_background_tasks()
            self._executor.shutdown(wait=True)
    
    def clear_all_alerts(self) -> bool:
        """Clear all alerts from buffer (for testing)."""
        return self.storage.clear_all_alerts()