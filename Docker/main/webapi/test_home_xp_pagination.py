"""XP ranking and database-tail pagination, including full-page boundaries."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from webapi.routers import system


class HomeXpPaginationTest(unittest.TestCase):
    def walk(self, ranked_count, tail_count):
        ranked = [{"source": "works", "arcid": f"rank-{i}"} for i in range(ranked_count)]
        tail = [{"source": "works", "arcid": f"tail-{i}"} for i in range(tail_count)]
        request = SimpleNamespace(state=SimpleNamespace(auth_user={"uid": "test"}))

        def tail_rows(**kwargs):
            self.assertEqual(kwargs["ranked_arcids"], [row["arcid"] for row in ranked])
            start = kwargs["offset"]
            return tail[start:start + kwargs["limit"]]

        pages = []
        cursor = ""
        with patch.object(system, "resolve_config", return_value=({}, {})), \
             patch.object(system, "get_local_recommendation_items_cached", return_value={"items": ranked}), \
             patch.object(system, "query_rows", return_value=[]), \
             patch.object(system, "_local_feed_tail_rows", side_effect=tail_rows), \
             patch.object(system, "_item_from_work", side_effect=lambda row, cfg: row):
            for _ in range(10):
                page = system.home_local(
                    request, cursor=cursor, limit=24, sort_by="xp", sort_order="desc",
                    include_categories="", include_tags="", min_rating=0,
                )
                pages.append(page)
                if not page["has_more"]:
                    break
                self.assertTrue(page["next_cursor"])
                self.assertNotEqual(page["next_cursor"], cursor)
                cursor = page["next_cursor"]
            else:
                self.fail("pagination never terminates")
        actual = [row["arcid"] for page in pages for row in page["items"]]
        expected = [row["arcid"] for row in ranked + tail]
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual), len(set(actual)))
        return pages

    def test_full_ranked_page_still_announces_the_database_tail(self):
        pages = self.walk(24, 2)
        self.assertEqual([len(p["items"]) for p in pages], [24, 2])

    def test_two_full_ranked_pages_can_continue_into_the_tail(self):
        self.walk(48, 25)

    def test_partial_ranked_page_blends_with_tail_without_gaps(self):
        pages = self.walk(44, 25)
        self.assertEqual([len(p["items"]) for p in pages], [24, 24, 21])

    def test_exact_total_boundary_has_no_extra_empty_page(self):
        pages = self.walk(24, 24)
        self.assertEqual([len(p["items"]) for p in pages], [24, 24])

    def test_ranking_without_a_tail_stops_at_its_actual_end(self):
        self.walk(48, 0)


if __name__ == "__main__":
    unittest.main()
