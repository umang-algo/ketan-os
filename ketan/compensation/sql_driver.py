"""
SQL Database Compensation Driver for Ketan-OS (केतन).

Constructs inverse SQL queries (e.g. inverse DELETE for INSERT) to compensate database mutations.
"""

import logging
from typing import Dict, Any, Optional, Callable

logger = logging.getLogger("SQLCompensationDriver")


class SQLCompensationDriver:
    """Out-of-the-box compensation driver for SQL database mutations."""
    
    @staticmethod
    def create_insert_compensation(
        table_name: str,
        primary_key_col: str,
        primary_key_val: Any,
        db_executor: Callable[[str], None]
    ) -> Callable[[Dict[str, Any], Any], None]:
        """Creates a compensation handler that executes an inverse DELETE query for an INSERT operation."""
        def compensate_insert(args: Dict[str, Any], result: Any) -> None:
            inverse_query = f"DELETE FROM {table_name} WHERE {primary_key_col} = '{primary_key_val}';"
            logger.info(f"[SQLCompensationDriver] Executing inverse query: {inverse_query}")
            db_executor(inverse_query)
            
        return compensate_insert
