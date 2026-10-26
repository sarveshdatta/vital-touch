"""Vital-sign validation and alert rules for Vital Touch.

Pure functions only, so they can be unit-tested without the web server.
Thresholds are screening defaults for adults, not clinical diagnosis.
"""

HR_LOW = 60          # bpm, below -> bradycardia warning
HR_HIGH = 100        # bpm, above -> tachycardia warning
SPO2_WARNING = 95    # %, below -> warning
SPO2_CRITICAL = 90   # %, below -> critical
TEMP_HIGH = 37.5     # deg C, above -> fever warning
TEMP_LOW = 35.0      # deg C, below -> hypothermia critical

# Physically plausible ranges; anything outside is treated as a sensor error.
VALID_RANGES = {
    "heart_rate": (20, 250),
    "spo2": (50, 100),
    "temperature": (25.0, 45.0),
}

LEVELS = ("normal", "warning", "critical")


def _raise_level(current, new):
    return new if LEVELS.index(new) > LEVELS.index(current) else current


def evaluate(heart_rate, spo2, temperature=None):
    """Return (status, issues) for one reading.

    status is 'normal', 'warning' or 'critical'; issues is a list of strings.
    temperature may be None when no temperature sensor is fitted.
    """
    status = "normal"
    issues = []

    if heart_rate > HR_HIGH:
        issues.append("Tachycardia (high heart rate)")
        status = _raise_level(status, "warning")
    elif heart_rate < HR_LOW:
        issues.append("Bradycardia (low heart rate)")
        status = _raise_level(status, "warning")

    if spo2 < SPO2_CRITICAL:
        issues.append("Low oxygen saturation (SpO2 below 90%)")
        status = _raise_level(status, "critical")
    elif spo2 < SPO2_WARNING:
        issues.append("Reduced oxygen saturation (SpO2 below 95%)")
        status = _raise_level(status, "warning")

    if temperature is not None:
        if temperature > TEMP_HIGH:
            issues.append("Elevated temperature (fever)")
            status = _raise_level(status, "warning")
        elif temperature < TEMP_LOW:
            issues.append("Low body temperature (hypothermia risk)")
            status = _raise_level(status, "critical")

    return status, issues


def _number(value, field, as_int, errors):
    if isinstance(value, bool) or value is None:
        errors.append(f"{field} must be a number")
        return None
    try:
        number = int(value) if as_int else round(float(value), 1)
    except (TypeError, ValueError):
        errors.append(f"{field} must be a number")
        return None
    low, high = VALID_RANGES[field]
    if not low <= number <= high:
        errors.append(f"{field} must be between {low} and {high}")
        return None
    return number


def validate_reading(payload):
    """Validate a JSON payload from a device.

    Returns (clean, errors). clean is None when errors is non-empty.
    """
    errors = []
    if not isinstance(payload, dict):
        return None, ["body must be a JSON object"]

    device_id = payload.get("device_id")
    if not isinstance(device_id, str) or not 1 <= len(device_id.strip()) <= 32:
        errors.append("device_id must be a string of 1-32 characters")

    heart_rate = _number(payload.get("heart_rate"), "heart_rate", True, errors)
    spo2 = _number(payload.get("spo2"), "spo2", True, errors)

    temperature = None
    if payload.get("temperature") is not None:
        temperature = _number(payload.get("temperature"), "temperature", False, errors)

    if errors:
        return None, errors
    return {
        "device_id": device_id.strip(),
        "heart_rate": heart_rate,
        "spo2": spo2,
        "temperature": temperature,
    }, []
