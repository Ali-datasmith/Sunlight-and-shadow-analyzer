import math
import datetime
from geometry import Vec3

EL_MIN_DEG = 2.0

class SunState:
    """Encapsulates astronomical solar position and geometric flags."""
    def __init__(
        self,
        azimuth_deg: float,
        elevation_deg: float,
        is_daytime: bool,
        shadows_active: bool,
        declination_deg: float,
        eot_min: float,
        hour_angle_deg: float
    ):
        self.azimuth_deg = float(azimuth_deg)
        self.elevation_deg = float(elevation_deg)
        self.is_daytime = bool(is_daytime)
        self.shadows_active = bool(shadows_active)
        self.declination_deg = float(declination_deg)
        self.eot_min = float(eot_min)
        self.hour_angle_deg = float(hour_angle_deg)

    def __repr__(self) -> str:
        return (
            f"SunState(az={self.azimuth_deg:.2f}°, el={self.elevation_deg:.2f}°, "
            f"day={self.is_daytime}, shadow={self.shadows_active})"
        )


def julian_day(y: int, m: int, d: int, t: float, tz: float) -> float:
    """Calculates Julian Day from Gregorian date, local minutes, and UTC timezone offset."""
    ordinal_day = datetime.date(y, m, d).toordinal()
    return ordinal_day + 1721424.5 + t / 1440.0 - tz / 24.0


def refraction_arcsec(el_g: float) -> float:
    """Computes atmospheric refraction correction in arcseconds based on geometric elevation."""
    h = el_g
    if h > 85.0:
        return 0.0
    elif h > 5.0:
        tan_h = math.tan(math.radians(h))
        return 58.1 / tan_h - 0.07 / (tan_h ** 3) + 0.000086 / (tan_h ** 5)
    elif h > -0.575:
        return 1735.0 + h * (-518.2 + h * (103.4 + h * (-12.79 + 0.711 * h)))
    else:
        tan_h = math.tan(math.radians(h))
        return -20.772 / tan_h


def solar_position(
    lat: float,
    lon: float,
    date: tuple[int, int, int],
    minutes: float,
    tz: float
) -> SunState:
    """Computes solar azimuth, elevation, and properties using NOAA General Solar Position Calculations."""
    y, m, d = date
    jd = julian_day(y, m, d, minutes, tz)
    jc = (jd - 2451545.0) / 36525.0

    l0 = (280.46646 + jc * (36000.76983 + 0.0003032 * jc)) % 360.0
    m_deg = 357.52911 + jc * (35999.05029 - 0.0001537 * jc)
    m_rad = math.radians(m_deg)

    e = 0.016708634 - jc * (0.000042037 + 0.0000001267 * jc)
    c = (
        math.sin(m_rad) * (1.914602 - jc * (0.004817 + 0.000014 * jc))
        + math.sin(2.0 * m_rad) * (0.019993 - 0.000101 * jc)
        + 0.000289 * math.sin(3.0 * m_rad)
    )

    true_long = l0 + c
    omega = 125.04 - 1934.136 * jc
    omega_rad = math.radians(omega)
    lam_app = true_long - 0.00569 - 0.00478 * math.sin(omega_rad)
    lam_app_rad = math.radians(lam_app)

    eps0 = 23.0 + (26.0 + (21.448 - jc * (46.815 + jc * (0.00059 - 0.001813 * jc))) / 60.0) / 60.0
    eps = eps0 + 0.00256 * math.cos(omega_rad)
    eps_rad = math.radians(eps)

    sin_delta = math.sin(eps_rad) * math.sin(lam_app_rad)
    delta_rad = math.asin(max(-1.0, min(1.0, sin_delta)))
    delta_deg = math.degrees(delta_rad)

    y_tan = math.tan(eps_rad / 2.0) ** 2
    l0_rad = math.radians(l0)
    eot = 4.0 * math.degrees(
        y_tan * math.sin(2.0 * l0_rad)
        - 2.0 * e * math.sin(m_rad)
        + 4.0 * e * y_tan * math.sin(m_rad) * math.cos(2.0 * l0_rad)
        - 0.5 * (y_tan ** 2) * math.sin(4.0 * l0_rad)
        - 1.25 * (e ** 2) * math.sin(2.0 * m_rad)
    )

    tst = (minutes + eot + 4.0 * lon - 60.0 * tz) % 1440.0
    h_deg = tst / 4.0 - 180.0
    if h_deg < -180.0:
        h_deg += 360.0
    h_rad = math.radians(h_deg)

    phi_rad = math.radians(lat)
    cos_z = math.sin(phi_rad) * math.sin(delta_rad) + math.cos(phi_rad) * math.cos(delta_rad) * math.cos(h_rad)
    cos_z = max(-1.0, min(1.0, cos_z))
    theta_z = math.acos(cos_z)
    theta_z_deg = math.degrees(theta_z)
    el_g = 90.0 - theta_z_deg

    sin_z = math.sin(theta_z)
    if sin_z < 1e-9:
        az = 180.0
    else:
        denom = math.cos(phi_rad) * sin_z
        val = (math.sin(phi_rad) * cos_z - math.sin(delta_rad)) / denom
        val = max(-1.0, min(1.0, val))
        psi = math.degrees(math.acos(val))
        if h_deg > 0:
            az = (psi + 180.0) % 360.0
        else:
            az = (540.0 - psi) % 360.0

    r_arcsec = refraction_arcsec(el_g)
    el = el_g + r_arcsec / 3600.0

    is_daytime = (el > 0.0)
    shadows_active = (el >= EL_MIN_DEG)
    return SunState(az, el, is_daytime, shadows_active, delta_deg, eot, h_deg)


def sun_vector(az_deg: float, el_deg: float) -> Vec3:
    """Returns the unit direction vector pointing from surface toward the sun in ENU coordinates."""
    a = math.radians(az_deg)
    e = math.radians(el_deg)
    return Vec3(
        math.cos(e) * math.sin(a),
        math.cos(e) * math.cos(a),
        math.sin(e)
    )


def sunrise_sunset(
    lat: float,
    lon: float,
    date: tuple[int, int, int],
    tz: float
) -> tuple[int | None, int | None]:
    """Scans minutes 0..1439 at 1-minute resolution to find first and last minute of daylight."""
    first_up: int | None = None
    last_up: int | None = None
    all_day = True

    for m in range(1440):
        sun = solar_position(lat, lon, date, float(m), tz)
        if sun.is_daytime:
            if first_up is None:
                first_up = m
            last_up = m
        else:
            all_day = False

    if first_up is None:
        # Polar night: sun never rises
        return (None, None)
    if all_day:
        # Midnight sun: 24h daylight
        return (0, 1439)
    return (first_up, last_up)


def run_checks() -> list[tuple[str, bool, str]]:
    """Self-test verification against reference cases S1-S5."""
    results = []
    lat, lon, tz = 31.5204, 74.3587, 5.0

    # S1 Equinox noon
    s1 = solar_position(lat, lon, (2024, 3, 21), 720.0, tz)
    s1_ok = abs(s1.azimuth_deg - 175.0) <= 2.0 and abs(s1.elevation_deg - 58.8) <= 1.0
    results.append(("Solar S1: Equinox noon", s1_ok, f"az={s1.azimuth_deg:.2f}°, el={s1.elevation_deg:.2f}°"))

    # S2 Solstice noon
    s2 = solar_position(lat, lon, (2024, 6, 21), 720.0, tz)
    s2_ok = abs(s2.azimuth_deg - 173.0) <= 4.0 and abs(s2.elevation_deg - 81.8) <= 1.0
    results.append(("Solar S2: Summer solstice noon", s2_ok, f"az={s2.azimuth_deg:.2f}°, el={s2.elevation_deg:.2f}°"))

    # S3 Winter noon
    s3 = solar_position(lat, lon, (2024, 12, 21), 720.0, tz)
    s3_ok = abs(s3.azimuth_deg - 180.0) <= 2.0 and abs(s3.elevation_deg - 35.0) <= 1.0
    results.append(("Solar S3: Winter solstice noon", s3_ok, f"az={s3.azimuth_deg:.2f}°, el={s3.elevation_deg:.2f}°"))

    # S4 Night
    s4 = solar_position(lat, lon, (2024, 3, 21), 120.0, tz)
    s4_ok = (not s4.is_daytime) and (not s4.shadows_active) and (s4.elevation_deg < 0.0)
    results.append(("Solar S4: Night time check", s4_ok, f"daytime={s4.is_daytime}, el={s4.elevation_deg:.2f}°"))

    # S5 Morning 10:00
    s5 = solar_position(lat, lon, (2024, 3, 21), 600.0, tz)
    s5_ok = abs(s5.azimuth_deg - 129.0) <= 2.0 and abs(s5.elevation_deg - 46.3) <= 1.5
    results.append(("Solar S5: Equinox 10:00 AM", s5_ok, f"az={s5.azimuth_deg:.2f}°, el={s5.elevation_deg:.2f}°"))

    # SC2 Shadow direction and length check
    bearing = (s5.azimuth_deg + 180.0) % 360.0
    tan_el = math.tan(math.radians(s5.elevation_deg))
    length_10m = 10.0 / tan_el
    sc2_ok = abs(bearing - 309.0) <= 2.0 and abs(length_10m - 9.6) <= 0.6
    results.append(("Solar SC2: Shadow bearing & length", sc2_ok, f"bearing={bearing:.1f}°, length={length_10m:.2f}m"))

    # Sunrise / sunset check
    sr, ss = sunrise_sunset(lat, lon, (2024, 3, 21), tz)
    sr_ok = sr is not None and ss is not None and (300 <= sr <= 400) and (1050 <= ss <= 1150)
    results.append(("Solar: Equinox sunrise/sunset scan", sr_ok, f"sunrise={sr}min, sunset={ss}min"))

    return results
