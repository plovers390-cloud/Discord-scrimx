from __future__ import annotations

import typing

if typing.TYPE_CHECKING:
    from core import Quotient

from tortoise import models

from .waiting import RoleWaiting

# __all__ list me bhi add karo
__all__ = [
    # ... existing models
    "RoleWaiting",
]


class BaseDbModel(models.Model):
    """Base Model for all tortoise models"""

    class Meta:
        abstract = True

    bot: Quotient


from .esports import *
from .helpers import *
from .misc import *
