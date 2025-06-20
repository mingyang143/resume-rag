from .helpers import compute_months_between
from dateutil import parser


if __name__ == "__main__":
    date1 = "10 Jun"
    date2 = "18 Jul/10 Oct"
    d1 = parser.parse(date1)
    d2 = parser.parse(date2)

    delta_days = (d2 - d1).days
    print(f"Months between {date1} and {date2}: {delta_days/30.0}")