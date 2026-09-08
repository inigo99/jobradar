"""Getting the data out.

A job search outlives any one tool, and people want their pipeline in a
spreadsheet — to share with someone, to sort in ways no dashboard anticipated,
or simply to keep after they stop using JobRadar. Both exporters write every
field the dashboard shows, including the user's own tracking notes.
"""

from .csv_export import export_csv
from .excel_export import export_excel

__all__ = ["export_csv", "export_excel"]
