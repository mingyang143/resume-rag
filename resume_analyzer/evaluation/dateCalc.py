from dateutil import parser

d1 = parser.parse("June")
d2 = parser.parse("Aug 2026")

delta = d2 - d1
print(delta.days)
print(d1.year, d1.month, d1.day)
print(d2.year, d2.month, d2.day)
