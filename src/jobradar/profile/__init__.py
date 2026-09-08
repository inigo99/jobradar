"""Building and maintaining the candidate profile.

The profile is the contract at the centre of JobRadar: the scorer measures
against it, the tailoring step draws from it, and the validator refuses
anything a generated document says that the profile does not support. Getting
it right once is what makes every later document trustworthy.
"""

from .importer import extract_text, import_profile, profile_from_form
from .vocabulary import allowed_terms, derive_evidence, suggest_ceilings

__all__ = [
    "extract_text",
    "import_profile",
    "profile_from_form",
    "allowed_terms",
    "derive_evidence",
    "suggest_ceilings",
]
