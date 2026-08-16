"""
SQL Database Compensation Driver for Ketan-OS (केतन).

Constructs parameterized inverse SQL queries (e.g. inverse DELETE for INSERT) to compensate database mutations safely.
"""

import re
import logging
from typing import Dict, Any, Optional, Callable, Tuple

logger = logging.getLogger("SQLCompensationDriver")


class SQLCompensationDriver:
    """Out-of-the-box safe parameterized compensation driver for SQL database mutations."""
    
    @staticmethod
    def _sanitize_identifier(identifier: str) -> str:
        """Validates SQL table and column identifiers against strict alphanumeric pattern."""
        if not re.match(r"^[A-Za-z0-9_]+$", identifier):
            raise ValueError(f"Unsafe SQL identifier: '{identifier}'. Identifiers must be alphanumeric with underscores.")
        return identifier

    @staticmethod
    def create_insert_compensation(
        table_name: str,
        primary_key_col: str,
        primary_key_val: Any,
        db_executor: Callable[[str, Tuple[Any, ...]], None]
    ) -> Callable[[Dict[str, Any], Any], None]:
        """
        Creates a safe compensation handler that executes a parameterized inverse DELETE query for an INSERT operation.
        Prevents SQL injection by sanitizing identifiers and binding parameters.
        """
        safe_table = SQLCompensationDriver._sanitize_identifier(table_name)
        safe_col = SQLCompensationDriver._sanitize_identifier(primary_key_col)
        
        def compensate_insert(args: Dict[str, Any], result: Any) -> None:
            inverse_query = f"DELETE FROM {safe_table} WHERE {safe_col} = ?"
            logger.info(f"[SQLCompensationDriver] Executing safe inverse query: {inverse_query} with params ({primary_key_val},)")
            db_executor(inverse_query, (primary_key_val,))
            
        return compensate_insert
