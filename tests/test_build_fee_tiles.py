import unittest

from scripts.build_fee_tiles import place_on_grid


class PlaceOnGridTests(unittest.TestCase):
    def test_tiles_keep_their_compass_order_in_their_own_cells(self):
        spots = {"북": (127.0, 38.0), "남": (127.0, 36.0), "서": (126.0, 37.0), "동": (128.0, 37.0), "가운데": (127.0, 37.0)}
        columns, rows, placed = place_on_grid(spots)
        self.assertEqual(len(set(placed.values())), 5)
        self.assertTrue(all(0 <= c < columns and 0 <= r < rows for c, r in placed.values()))
        self.assertLess(placed["북"][1], placed["남"][1])
        self.assertLess(placed["서"][0], placed["동"][0])

    def test_a_district_without_places_still_gets_a_cell_and_one_district_one_cell(self):
        _, _, placed = place_on_grid({"가": (127.0, 37.0), "나": (127.5, 36.5), "다": None})
        self.assertEqual(len(set(placed.values())), 3)
        self.assertEqual(place_on_grid({"세종": None}), (1, 1, {"세종": (0, 0)}))

    def test_no_empty_row_or_column_is_left(self):
        columns, rows, _ = place_on_grid({"제주시": (126.5, 33.5), "서귀포시": (126.5, 33.25)})
        self.assertEqual((columns, rows), (1, 2))


if __name__ == "__main__":
    unittest.main()
