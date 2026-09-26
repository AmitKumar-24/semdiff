"""Built-in rule families. Importing this package registers them into ``BUILTIN_RULES``."""

from semdiff.normalize.registry import BUILTIN_RULES
from semdiff.normalize.rules.assets import ASSET_RULES
from semdiff.normalize.rules.canonical import CANONICAL_RULES
from semdiff.normalize.rules.classes import CLASS_RULES
from semdiff.normalize.rules.ids import ID_RULES
from semdiff.normalize.rules.timestamps import TIMESTAMP_RULES
from semdiff.normalize.rules.tokens import TOKEN_RULES

for _rule in CLASS_RULES + ID_RULES + TOKEN_RULES + TIMESTAMP_RULES + ASSET_RULES + CANONICAL_RULES:
    BUILTIN_RULES.register(_rule)
