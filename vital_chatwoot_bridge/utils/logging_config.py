#!/usr/bin/env python3
"""
Centralized logging configuration for the Vital Chatwoot Bridge.
Ensures consistent logging setup across all modules and scripts.
"""

import logging
import os
import sys
from typing import Optional


def setup_logging(
    level: Optional[str] = None,
    format_string: Optional[str] = None,
    force_reconfigure: bool = False
) -> None:
    """
    Set up logging configuration for the application.
    
    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        format_string: Custom format string for log messages
        force_reconfigure: Force reconfiguration even if logging is already set up
    """
    # Get log level from parameter, environment, or default to INFO
    if level is None:
        level = os.getenv('LOG_LEVEL', 'INFO').upper()
    
    # Default format string
    if format_string is None:
        format_string = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    
    # Convert string level to logging constant
    numeric_level = getattr(logging, level, logging.INFO)
    
    # Get root logger
    root_logger = logging.getLogger()
    
    # Check if logging is already configured
    if root_logger.handlers and not force_reconfigure:
        # Just update the level if needed
        root_logger.setLevel(numeric_level)
        for handler in root_logger.handlers:
            handler.setLevel(numeric_level)
        return
    
    # Clear existing handlers if force reconfigure
    if force_reconfigure:
        root_logger.handlers.clear()
    
    # Configure logging
    logging.basicConfig(
        level=numeric_level,
        format=format_string,
        stream=sys.stdout,
        force=force_reconfigure
    )
    
    # Set the root logger level
    root_logger.setLevel(numeric_level)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger with the specified name.
    Ensures logging is set up if not already configured.
    
    Args:
        name: Logger name (typically __name__)
        
    Returns:
        Configured logger instance
    """
    # Ensure logging is set up
    setup_logging()
    
    return logging.getLogger(name)


# Auto-configure logging when this module is imported
setup_logging()
