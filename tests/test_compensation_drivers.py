"""Tests for Ketan-OS Out-of-the-Box Compensation Drivers."""
import unittest
from ketan.compensation import GitCompensationDriver, SQLCompensationDriver


class TestCompensationDrivers(unittest.TestCase):
    def test_sql_compensation_driver_query_generation(self):
        executed_queries = []
        def mock_db_exec(query: str):
            executed_queries.append(query)

        handler = SQLCompensationDriver.create_insert_compensation(
            table_name="orders",
            primary_key_col="order_id",
            primary_key_val="ORD_999",
            db_executor=mock_db_exec
        )

        handler({"table": "orders"}, "SUCCESS")
        self.assertEqual(len(executed_queries), 1)
        self.assertEqual(executed_queries[0], "DELETE FROM orders WHERE order_id = 'ORD_999';")


if __name__ == "__main__":
    unittest.main()
