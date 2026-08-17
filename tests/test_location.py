from __future__ import annotations

from mypicsdb3.location import format_coordinates, location_details_from_row


def test_location_details_normalize_named_fields_and_coordinates() -> None:
    details = location_details_from_row(
        {
            "country": " Sweden ",
            "state": "Stockholm County",
            "city": " Stockholm ",
            "sublocation": " Gamla stan ",
            "gps_latitude": 59.3251172,
            "gps_longitude": 18.0710921,
        }
    )

    assert details.country == "Sweden"
    assert details.city == "Stockholm"
    assert details.has_named_location is True
    assert details.coordinates == (59.3251172, 18.0710921)
    assert format_coordinates(details) == "59.325117, 18.071092"


def test_location_details_can_hide_coordinates_for_privacy_setting() -> None:
    details = location_details_from_row(
        {
            "country": "Sweden",
            "gps_latitude": 59.3251172,
            "gps_longitude": 18.0710921,
        },
        include_coordinates=False,
    )

    assert details.country == "Sweden"
    assert details.coordinates is None
    assert format_coordinates(details) == ""


def test_location_details_require_a_valid_coordinate_pair() -> None:
    assert location_details_from_row(
        {"gps_latitude": 91, "gps_longitude": 18}
    ).coordinates is None
    assert location_details_from_row(
        {"gps_latitude": 59, "gps_longitude": None}
    ).coordinates is None
    assert location_details_from_row(
        {"gps_latitude": float("nan"), "gps_longitude": 18}
    ).coordinates is None
