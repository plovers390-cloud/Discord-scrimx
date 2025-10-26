from __future__ import annotations

import typing

if typing.TYPE_CHECKING:
    from core import Quotient

from contextlib import suppress

import discord

from core import Context
from utils import emote

class RoleRevertButton(discord.ui.Button):
    def __init__(self, ctx: Context, *, role: discord.Role = None, members: typing.List[discord.Member] = None, take_role=True, added_roles: typing.List[discord.Role] = None):
        super().__init__()

        self.emoji = emote.exit
        self.label = "Take Back" if take_role else "Give Back"
        self.custom_id = "role_revert_action_button"

        self.ctx = ctx
        self.role = role
        self.members = members or []
        self.take_role = take_role
        self.added_roles = added_roles or []  # New parameter for multiple roles

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        # If we have multiple roles (added_roles), use them
        if self.added_roles:
            for member in self.members:
                for role in self.added_roles:
                    with suppress(discord.HTTPException):
                        if self.take_role:
                            await member.remove_roles(role)
                        else:
                            await member.add_roles(role)
        # Otherwise use single role (backward compatibility)
        elif self.role:
            for member in self.members:
                with suppress(discord.HTTPException):
                    if self.take_role:
                        await member.remove_roles(self.role)
                    else:
                        await member.add_roles(self.role)

        # Disable the button after click
        self.disabled = True
        await interaction.message.edit(view=self.view)
        
        return await self.ctx.success("Successfully reverted the action.")


class RoleCancelButton(discord.ui.Button):
     def __init__(self, ctx: Context, *, role: discord.Role, members: typing.List[discord.Member]):
        super().__init__()
        self.ctx = ctx
        self.role = role
        self.members = members
