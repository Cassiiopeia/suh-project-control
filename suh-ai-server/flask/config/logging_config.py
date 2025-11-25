"""
Logging configuration
"""
import logging
import os


def setup_logging():
    """
    Setup logging configuration
    
    Returns:
        Logger instance
    """
    # Create logs directory if not exists
    logs_dir = os.path.join(os.path.dirname(__file__), '..', 'logs')
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )
    
    return logging.getLogger(__name__)

