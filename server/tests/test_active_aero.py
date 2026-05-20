from active_aero import is_z_mode, CIRCUIT_AERO_ZONES, get_circuit_aero_zones


class TestIsZMode:
    def test_path_a_channel_active_returns_true(self):
        assert is_z_mode(120, 400, "monza", aero_state_channel=1) is True

    def test_path_a_channel_zero_returns_false(self):
        assert is_z_mode(330, 2500, "belgium", aero_state_channel=0) is False

    def test_path_b_in_zone_high_speed_returns_true(self):
        # Kemmel straight runs 1900-3100 in the belgium profile.
        assert is_z_mode(320, 2400, "belgium") is True

    def test_path_b_outside_zone_returns_false(self):
        # On italy / Monza the first zone is start_finish 0-1100; 400m at low
        # speed is well outside any reasonable Z-mode trigger.
        assert is_z_mode(120, 400, "italy") is False

    def test_path_b_first_100m_transition_lag(self):
        # 1950m is inside the Kemmel zone but within the 100m transition window.
        assert is_z_mode(320, 1950, "belgium") is False

    def test_path_b_unknown_circuit_returns_false(self):
        assert is_z_mode(320, 2400, "nonexistent-circuit") is False

    def test_path_b_low_speed_in_zone_returns_false(self):
        # In Kemmel zone but speed below the 250 km/h threshold.
        assert is_z_mode(200, 2400, "belgium") is False


class TestCircuitAeroZones:
    def test_coverage_at_least_80_percent_of_2026_calendar(self):
        assert len(CIRCUIT_AERO_ZONES) >= 19, (
            f"Only {len(CIRCUIT_AERO_ZONES)} circuits in CIRCUIT_AERO_ZONES; "
            f"target >= 19 (80% of 24)"
        )

    def test_each_entry_has_required_fields(self):
        for slug, profile in CIRCUIT_AERO_ZONES.items():
            assert "circuit_country" in profile, f"{slug} missing circuit_country"
            assert "zones" in profile, f"{slug} missing zones"
            assert "last_reviewed" in profile, f"{slug} missing last_reviewed"
            assert "source" in profile, f"{slug} missing source"
            for zone in profile["zones"]:
                assert "start_distance_m" in zone, f"{slug} zone missing start_distance_m"
                assert "end_distance_m" in zone, f"{slug} zone missing end_distance_m"
                assert zone["end_distance_m"] > zone["start_distance_m"], (
                    f"{slug} zone has invalid distances"
                )

    def test_get_circuit_aero_zones_returns_zones_for_known_circuit(self):
        zones = get_circuit_aero_zones("belgium")
        assert zones is not None
        assert len(zones) >= 1

    def test_get_circuit_aero_zones_returns_none_for_unknown(self):
        assert get_circuit_aero_zones("nonexistent") is None
