import unittest

from src.supabase_store import where_sql


class WhereSqlTests(unittest.TestCase):
    """Chroma's where dicts become jsonb conditions for the Supabase store (ADR-0007)."""

    def test_shapes_the_app_sends(self):
        self.assertEqual(where_sql(None), ("true", []))
        self.assertEqual(where_sql({"meta.lifeCycle": "성견"}), ("metadata ->> %s = %s", ["meta.lifeCycle", "성견"]))
        sql, params = where_sql({"$or": [{"meta.disease": "기타"}, {"meta.disease": "해당없음"}]})
        self.assertEqual(sql, "(metadata ->> %s = %s or metadata ->> %s = %s)")
        self.assertEqual(params, ["meta.disease", "기타", "meta.disease", "해당없음"])
        sql, params = where_sql({"$and": [{"meta.department": "내과"}, {"meta.lifeCycle": {"$in": ["성견", "노령견"]}}]})
        self.assertEqual(sql, "(metadata ->> %s = %s and metadata ->> %s = any(%s))")
        self.assertEqual(params, ["meta.department", "내과", "meta.lifeCycle", ["성견", "노령견"]])


if __name__ == "__main__":
    unittest.main()
