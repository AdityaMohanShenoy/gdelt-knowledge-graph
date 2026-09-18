"""
Shared utilities for the GDELT pipeline.
"""

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_path(*parts) -> str:
    return os.path.join(ROOT, *parts)


# CAMEO country code -> country name (full list, GDELT FIPS codes)
COUNTRY_NAMES = {
    "US": "United States", "IS": "Israel", "UP": "Palestine / West Bank",
    "RS": "Russia", "IN": "India", "UK": "United Kingdom",
    "PK": "Pakistan", "NI": "Nicaragua", "DJ": "Djibouti", "AS": "Australia",
    "CH": "China", "FR": "France", "GM": "Germany", "IT": "Italy",
    "JA": "Japan", "BR": "Brazil", "SF": "South Africa", "EG": "Egypt",
    "IR": "Iran", "IZ": "Iraq", "SY": "Syria", "YM": "Yemen",
    "AF": "Afghanistan", "TU": "Turkey", "SA": "Saudi Arabia",
    "UAE": "United Arab Emirates", "LE": "Lebanon", "JO": "Jordan",
    "CA": "Canada", "MX": "Mexico", "AR": "Argentina", "CL": "Chile",
    "CO": "Colombia", "VE": "Venezuela", "PE": "Peru", "BO": "Bolivia",
    "RO": "Romania", "PL": "Poland", "HU": "Hungary", "CZ": "Czech Republic",
    "AU": "Austria", "SW": "Sweden", "NO": "Norway", "FI": "Finland",
    "DA": "Denmark", "SP": "Spain", "PO": "Portugal", "GR": "Greece",
    "BU": "Bulgaria", "AL": "Albania", "HR": "Croatia", "SR": "Serbia",
    "BO": "Bosnia and Herzegovina", "MK": "North Macedonia",
    "NG": "Nigeria", "KE": "Kenya", "ET": "Ethiopia", "GH": "Ghana",
    "SN": "Senegal", "TZ": "Tanzania", "UG": "Uganda", "MO": "Morocco",
    "TN": "Tunisia", "LY": "Libya", "SD": "Sudan", "SO": "Somalia",
    "TH": "Thailand", "MY": "Malaysia", "ID": "Indonesia",
    "PH": "Philippines", "VN": "Vietnam", "MM": "Myanmar",
    "BD": "Bangladesh", "NP": "Nepal", "LK": "Sri Lanka",
    "KZ": "Kazakhstan", "UZ": "Uzbekistan", "TM": "Turkmenistan",
    "KG": "Kyrgyzstan", "TJ": "Tajikistan",
    "NZ": "New Zealand", "FJ": "Fiji",
}


def lookup_country(code: str) -> str:
    return COUNTRY_NAMES.get(code, code)


# CAMEO root event code -> description
EVENT_ROOT_CODES = {
    "01": "Make Public Statement",
    "02": "Appeal",
    "03": "Express Intent to Cooperate",
    "04": "Consult",
    "05": "Engage in Diplomatic Cooperation",
    "06": "Engage in Material Cooperation",
    "07": "Provide Aid",
    "08": "Yield",
    "09": "Investigate",
    "10": "Demand",
    "11": "Disapprove",
    "12": "Reject",
    "13": "Threaten",
    "14": "Protest",
    "15": "Exhibit Military Posture",
    "16": "Reduce Relations",
    "17": "Coerce",
    "18": "Assault",
    "19": "Fight",
    "20": "Engage in Unconventional Mass Violence",
}


def lookup_event_root(code: str) -> str:
    return EVENT_ROOT_CODES.get(str(code).zfill(2), f"Code {code}")


QUAD_CLASS = {
    "1": "Verbal Cooperation",
    "2": "Material Cooperation",
    "3": "Verbal Conflict",
    "4": "Material Conflict",
}


def lookup_quad(code: str) -> str:
    return QUAD_CLASS.get(str(code), str(code))
