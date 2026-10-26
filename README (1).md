# Sample data

`sample_readings.json` holds 20 readings in the exact format the ESP32 sends
to `POST /api/readings`. They cover every alert path:

| Readings | Case | Expected status |
|---|---|---|
| 1-5, 8, 11-12, 18-19 | Normal values (8 sits exactly on the thresholds) | normal |
| 6-7 | Heart rate above 100 bpm | warning |
| 9 | SpO2 93% | warning |
| 10 | SpO2 89% | critical |
| 13-14 | Temperature above 37.5 °C | warning |
| 15-16 | Heart rate below 60 bpm | warning |
| 17 | Temperature 34.6 °C | critical |
| 20 | HR 118, SpO2 87%, 38.1 °C | critical |

Readings 1-10 have no `temperature` field, which is what the firmware sends
when no MLX90614 is fitted.

Replay them into a running backend (no hardware needed):

```bash
python tools/replay_sample_data.py --url http://localhost:5000 --key <VT_DEVICE_API_KEY>
```
