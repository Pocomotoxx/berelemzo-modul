import unittest

from berelemzo.stats import norm_cdf, t_sf, t_upper_quantile


class StatsTests(unittest.TestCase):
    def test_norm_cdf(self):
        self.assertAlmostEqual(norm_cdf(0.0), 0.5, places=12)
        self.assertAlmostEqual(norm_cdf(1.644853627), 0.95, places=7)

    def test_t_quantiles_match_tables(self):
        # Student-féle t, egyoldali 5%: ismert táblázati értékek
        for df, expected in ((1, 6.313752), (5, 2.015048), (10, 1.812461), (30, 1.697261), (100, 1.660234)):
            self.assertAlmostEqual(t_upper_quantile(0.05, df), expected, places=5, msg=f"df={df}")

    def test_t_sf_symmetry_and_large_df(self):
        self.assertAlmostEqual(t_sf(0.0, 7), 0.5, places=12)
        self.assertAlmostEqual(t_sf(-1.3, 9) + t_sf(1.3, 9), 1.0, places=12)
        self.assertAlmostEqual(t_upper_quantile(0.05, 1e6), 1.644854, places=4)

    def test_non_integer_df_matches_reference_values(self):
        # a scipy.stats.t.ppf(0,95, df) értékei, rögzítve (a szkript nem függ a scipy-tól)
        ref = {2.5: 2.5582186141359355, 7.3: 1.8829300179564308, 19.9: 1.725138790921033,
               48.2: 1.6770872569879265, 233.0: 1.6514196466104323}
        for df, expected in ref.items():
            self.assertAlmostEqual(t_upper_quantile(0.05, df), expected, places=8)


if __name__ == "__main__":
    unittest.main()
