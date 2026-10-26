import pytest

from alerts import evaluate, validate_reading


@pytest.mark.parametrize(
    "hr, spo2, temp, expected_status",
    [
        (75, 98, 36.8, "normal"),
        (75, 98, None, "normal"),       # no temperature sensor fitted
        (110, 98, None, "warning"),     # tachycardia
        (52, 98, None, "warning"),      # bradycardia
        (75, 93, None, "warning"),      # reduced SpO2
        (75, 88, None, "critical"),     # SpO2 below 90
        (75, 98, 38.2, "warning"),      # fever
        (75, 98, 34.5, "critical"),     # hypothermia
        (60, 95, 37.5, "normal"),       # exact thresholds are still normal
        (100, 95, None, "normal"),
    ],
)
def test_evaluate_status(hr, spo2, temp, expected_status):
    status, _ = evaluate(hr, spo2, temp)
    assert status == expected_status


def test_critical_is_not_downgraded_by_later_warning():
    # SpO2 critical + fever warning must stay critical
    status, issues = evaluate(120, 85, 38.5)
    assert status == "critical"
    assert len(issues) == 3


def test_validate_accepts_minimal_payload():
    clean, errors = validate_reading({"device_id": "ESP32_01", "heart_rate": "72", "spo2": 97})
    assert errors == []
    assert clean == {"device_id": "ESP32_01", "heart_rate": 72, "spo2": 97, "temperature": None}


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {"heart_rate": 72, "spo2": 97},                                   # missing device_id
        {"device_id": "ESP32_01", "spo2": 97},                            # missing heart_rate
        {"device_id": "ESP32_01", "heart_rate": 300, "spo2": 97},         # implausible HR
        {"device_id": "ESP32_01", "heart_rate": 72, "spo2": 101},         # SpO2 > 100
        {"device_id": "ESP32_01", "heart_rate": True, "spo2": 97},        # bool is not a number
        {"device_id": "ESP32_01", "heart_rate": 72, "spo2": 97, "temperature": 60},
        {"device_id": "x" * 40, "heart_rate": 72, "spo2": 97},
    ],
)
def test_validate_rejects_bad_payloads(payload):
    clean, errors = validate_reading(payload)
    assert clean is None
    assert errors
