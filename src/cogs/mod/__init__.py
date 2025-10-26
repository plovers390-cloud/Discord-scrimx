from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional, Union

if TYPE_CHECKING:
    from core import Quotient

import re

import discord
from discord.ext import commands

from constants import LockType
from core import Cog, Context, QuotientView, role_command_check
from models import Lockdown
from utils import ActionReason, BannedMember, FutureTime, MemberID, QuoUser, human_timedelta, plural
from utils import emote

from .events import *
from .utils import _complex_cleanup_strategy, _self_clean_system, do_removal
from .views import *


class Mod(Cog):
    def __init__(self, bot: Quotient):
        self.bot = bot

    @commands.command(aliases=["mr"])
    @commands.has_guild_permissions(manage_roles=True)
    @commands.bot_has_guild_permissions(manage_roles=True)
    @commands.cooldown(4, 1, type=commands.BucketType.guild)
    async def addmultipleroles(self, ctx: Context, member: discord.Member, *roles: discord.Role):
     """
      Add multiple roles to a member at once.
    
    Example:
    {prefix}addmultipleroles @user @role1 @role2 @role3
    {prefix}amr @user @role1 @role2 @role3
    """
     if not roles:
         return await ctx.error("Please provide at least one role to add.")
 
    # Check if bot has permission to assign all roles
     bot_top_role = ctx.guild.me.top_role
     for role in roles:
        if role >= bot_top_role:
            return await ctx.error(f"I cannot assign {role.mention} as it is higher than or equal to my top role.")
        
        if not role.is_assignable():
            return await ctx.error(f"I cannot assign {role.mention} due to permission hierarchy.")

    # Check if author has permission to assign all roles
     author_top_role = ctx.author.top_role
     for role in roles:
        if role >= author_top_role and ctx.author != ctx.guild.owner:
            return await ctx.error(f"You cannot assign {role.mention} as it is higher than or equal to your top role.")

     reason = f"Action done by {ctx.author} (ID: {ctx.author.id})"
    
     # Check which roles the member already has
     roles_to_add = [role for role in roles if role not in member.roles]
     roles_already_have = [role for role in roles if role in member.roles]
    
     if not roles_to_add:
      return await ctx.error(f"{member.mention} already has all the specified roles.")

     m = await ctx.simple(f"{emote.Loading} Adding {plural(len(roles_to_add)):role} to {member.mention}...")

     success, failed = 0, 0
     added_roles = []

     for role in roles_to_add:
        try:
            await member.add_roles(role, reason=reason)
            success += 1
            added_roles.append(role)
        except discord.HTTPException:
            failed += 1

     # Create success message
     message = f"Successfully added {plural(success):role} to {member.mention}. (Failed: {failed})"
    
     if roles_already_have:
        message += f"\n{member.mention} already had {len(roles_already_have)} role(s)."

     if success > 0:
        # Create a view with revert button (using added_roles parameter)
        _view = QuotientView(ctx)
        _view.add_item(RoleRevertButton(ctx, members=[member], added_roles=added_roles, take_role=True))
        
        await ctx.safe_delete(m)
        _view.message = await ctx.success(message, view=_view)
     else:
        await ctx.safe_delete(m)
        await ctx.error(f"Failed to add any roles to {member.mention}.")

    @commands.command(aliases=["rmr"])
    @commands.has_guild_permissions(manage_roles=True)
    @commands.bot_has_guild_permissions(manage_roles=True)
    @commands.cooldown(4, 1, type=commands.BucketType.guild)
    async def removemultipleroles(self, ctx: Context, member: discord.Member, *roles: discord.Role):
     """
     Remove multiple roles from a member at once.
    
     Example:
     {prefix}removemultipleroles @user @role1 @role2 @role3
     {prefix}rmr @user @role1 @role2 @role3
     """
     if not roles:
        return await ctx.error("Please provide at least one role to remove.")

     # Check if bot has permission to remove all roles
     bot_top_role = ctx.guild.me.top_role
     for role in roles:
        if role >= bot_top_role:
            return await ctx.error(f"I cannot remove {role.mention} as it is higher than or equal to my top role.")
        
        if not role.is_assignable():
            return await ctx.error(f"I cannot remove {role.mention} due to permission hierarchy.")

     # Check if author has permission to remove all roles
     author_top_role = ctx.author.top_role
     for role in roles:
        if role >= author_top_role and ctx.author != ctx.guild.owner:
            return await ctx.error(f"You cannot remove {role.mention} as it is higher than or equal to your top role.")

     reason = f"Action done by {ctx.author} (ID: {ctx.author.id})"
    
     # Check which roles the member actually has
     roles_to_remove = [role for role in roles if role in member.roles]
     roles_not_have = [role for role in roles if role not in member.roles]
    
     if not roles_to_remove:
        return await ctx.error(f"{member.mention} doesn't have any of the specified roles.")

     # Create loading message
     loading_msg = await ctx.send(f"{emote.Loading} Removing {len(roles_to_remove)} roles from {member.mention}...")

     success, failed = 0, 0
     removed_roles = []

     for role in roles_to_remove:
        try:
            await member.remove_roles(role, reason=reason)
            success += 1
            removed_roles.append(role)
        except discord.HTTPException as e:
            print(f"Failed to remove role {role.name}: {e}")  # Debug print
            failed += 1

     # Create success message
     message = f"Successfully removed {success} role(s) from {member.mention}."
    
     if failed > 0:
        message += f" (Failed: {failed})"
    
     if roles_not_have:
        message += f"\n{member.mention} didn't have {len(roles_not_have)} role(s)."

     # Delete loading message
     await loading_msg.delete()

     if success > 0:
        # Create a view with revert button (take_role=False means we'll add back the roles on revert)
        from .views import RoleRevertButton
        _view = QuotientView(ctx)
        _view.add_item(RoleRevertButton(ctx, members=[member], added_roles=removed_roles, take_role=False))
        
        await ctx.success(message, view=_view)
     else:
        await ctx.error(f"Failed to remove any roles from {member.mention}.")

    @commands.command()
    @commands.has_permissions(manage_guild=True)
    @commands.cooldown(5, 1, type=commands.BucketType.user)
    async def selfclean(self, ctx: Context, search=100):
        """
        Clean ScrimX's messages,
        Note: If bot has `manage_messages` permissions then it will delete the command messages too.
        """
        strategy = _self_clean_system
        if ctx.channel.permissions_for(ctx.me).manage_messages:
            strategy = _complex_cleanup_strategy

        search = min(max(2, search), 1000)

        spammers = await strategy(ctx, search)
        deleted = sum(spammers.values())
        messages = [f'{deleted} message{" was" if deleted == 1 else "s were"} removed.']
        if deleted:
            messages.append("")
            spammers = sorted(spammers.items(), key=lambda t: t[1], reverse=True)
            messages.extend(f"- **{author}**: {count}" for author, count in spammers)

        await ctx.send("\n".join(messages), delete_after=10)

    @commands.group(invoke_without_command=True, aliases=["purge"])
    @commands.has_permissions(manage_messages=True)
    @commands.cooldown(7, 1, type=commands.BucketType.guild)
    async def clear(self, ctx: Context, Choice: Union[discord.Member, int], amount: int = 5):
        """
        An all in one purge command.
        Choice can be a Member or a number
        """
        if isinstance(Choice, discord.Member):
            await do_removal(ctx, amount, lambda e: e.author == Choice)

        elif isinstance(Choice, int):
            await do_removal(ctx, Choice, lambda e: not e.pinned)

        await ctx.message.delete()

    @clear.command()
    @commands.has_permissions(manage_messages=True)
    async def embeds(self, ctx, search=100):
        """Removes messages that have embeds in them."""
        await do_removal(ctx, search, lambda e: len(e.embeds))

    @clear.command()
    @commands.has_permissions(manage_messages=True)
    async def files(self, ctx, search=100):
        """Removes messages that have attachments in them."""
        await do_removal(ctx, search, lambda e: len(e.attachments))

    @clear.command()
    @commands.has_permissions(manage_messages=True)
    async def images(self, ctx, search=100):
        """Removes messages that have embeds or attachments."""
        await do_removal(ctx, search, lambda e: len(e.embeds) or len(e.attachments))

    @clear.command(name="all")
    @commands.has_permissions(manage_messages=True)
    async def _remove_all(self, ctx, search=100):
        """Removes all messages."""
        await do_removal(ctx, search, lambda e: not e.pinned)

    @clear.command()
    @commands.has_permissions(manage_messages=True)
    async def user(self, ctx, member: QuoUser, search=100):
        """Removes all messages by the member."""
        await do_removal(ctx, search, lambda e: e.author == member)

    @clear.command()
    @commands.has_permissions(manage_messages=True)
    async def contains(self, ctx, *, substr: str):
        """Removes all messages containing a substring.
        The substring must be at least 3 characters long.
        """
        if len(substr) < 3:
            await ctx.error("The substring length must be at least 3 characters.")
        else:
            await do_removal(ctx, 100, lambda e: substr in e.content)

    @clear.command(name="bot", aliases=["bots"])
    @commands.has_permissions(manage_messages=True)
    async def _bot(self, ctx, prefix=None, search=100):
        """Removes a bot user's messages and messages with their optional prefix."""

        def predicate(m):
            return (m.webhook_id is None and m.author.bot) or (prefix and m.content.startswith(prefix))

        await do_removal(ctx, search, predicate)

    @clear.command(name="emoji", aliases=["emojis"])
    @commands.has_permissions(manage_messages=True)
    async def _emoji(self, ctx, search=100):
        """Removes all messages containing custom emoji."""
        custom_emoji = re.compile(r"<a?:[a-zA-Z0-9\_]+:([0-9]+)>")

        def predicate(m):
            return custom_emoji.search(m.content)

        await do_removal(ctx, search, predicate)

    @clear.command(name="reactions")
    @commands.has_permissions(manage_messages=True)
    async def _reactions(self, ctx, search=100):
        """Removes all reactions from messages that have them."""
        if search > 2000:
            return await ctx.send(f"Too many messages to search for ({search}/2000)")

        total_reactions = 0
        async for message in ctx.history(limit=search, before=ctx.message):
            if message.reactions:
                total_reactions += sum(r.count for r in message.reactions)
                await message.clear_reactions()

        await ctx.success(f"Successfully removed {total_reactions} reactions.")

    @commands.command()
    @commands.has_permissions(kick_members=True)
    @commands.bot_has_guild_permissions(kick_members=True)
    @commands.cooldown(3, 1, type=commands.BucketType.user)
    async def kick(self, ctx, member: MemberID, *, reason: ActionReason = None):
        """Kicks a member from the server.
        In order for this to work, the bot must have Kick Member permissions.
        To use this command you must have Kick Members permission.
        """
        if reason is None:
            reason = f"Action done by {ctx.author} (ID: {ctx.author.id})"

        await ctx.guild.kick(member, reason=reason)
        await ctx.success(f"{str(member)} has been successfully kicked out!")

    @commands.command()
    @commands.has_permissions(ban_members=True)
    @commands.cooldown(3, 1, type=commands.BucketType.user)
    @commands.bot_has_guild_permissions(ban_members=True)
    async def ban(self, ctx, member: MemberID, *, reason: ActionReason = None):
        """Bans a member from the server.
        You can also ban from ID to ban regardless whether they're
        in the server or not.
        In order for this to work, the bot must have Ban Member permissions.
        To use this command you must have Ban Members permission.
        """
        if reason is None:
            reason = f"Action done by {ctx.author} (ID: {ctx.author.id})"

        await ctx.guild.ban(member, reason=reason)
        await ctx.success(f"{str(member)} has been successfully banned!")

    @commands.command()
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_guild_permissions(ban_members=True)
    @commands.cooldown(3, 1, type=commands.BucketType.user)
    async def unban(self, ctx: Context, member: BannedMember, *, reason: ActionReason = None):
        """Unbans a member from the server.
        You can pass either the ID of the banned member or the Name#Discrim
        combination of the member. Typically the ID is easiest to use.
        In order for this to work, the bot must have Ban Member permissions.
        To use this command you must have Ban Members permissions.
        """
        if reason is None:
            reason = f"Action done by {ctx.author} (ID: {ctx.author.id})"

        await ctx.guild.unban(member.user, reason=reason)
        if member.reason:
            await ctx.send(f"Unbanned {member.user} (ID: {member.user.id}), previously banned for {member.reason}.")
        else:
            await ctx.success(f"Unbanned {member.user} (ID: {member.user.id}).")

    @commands.group(
        invoke_without_command=True,
        aliases=["addrole", "giverole"],
        extras={"examples": ["role @role @user1 @user2 @user3 ..."]},
     )
    @commands.has_guild_permissions(manage_roles=True)
    @commands.bot_has_guild_permissions(manage_roles=True)
    @commands.cooldown(4, 1, type=commands.BucketType.guild)
    async def role(self, ctx: Context, *args):
     """
    Add a role to one or multiple users.
     Usage: role @role @user1 @user2 OR role @user1 @user2 @role
     """
    
     if not args:
        return await ctx.error("Please provide a role and at least one member.")
    
     # Separate roles and members from arguments
     roles = []
     members = []
    
     for arg in args:
        try:
            # Try to convert to role
            role_conv = await commands.RoleConverter().convert(ctx, str(arg))
            roles.append(role_conv)
        except:
            try:
                # Try to convert to member
                member_conv = await commands.MemberConverter().convert(ctx, str(arg))
                members.append(member_conv)
            except:
                pass
    
     # Validate we have exactly one role
     if len(roles) == 0:
        return await ctx.error("Please specify a role to add.")
     elif len(roles) > 1:
        return await ctx.error("Please specify only one role.")
    
     role = roles[0]
    
     # Manual role checks (since we can't use the decorator)
     if role.managed:
        return await ctx.error(f"{role.mention} is a managed role (bot/integration role) and cannot be assigned manually.")
    
     if role.is_bot_managed():
        return await ctx.error(f"{role.mention} is managed by a bot and cannot be assigned manually.")
    
     if role.is_integration():
        return await ctx.error(f"{role.mention} is an integration role and cannot be assigned manually.")
    
     if role >= ctx.guild.me.top_role:
        return await ctx.error(f"{role.mention} is higher than or equal to my highest role. Please move my role above it.")
    
     if role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
        return await ctx.error(f"{role.mention} is higher than or equal to your highest role.")
    
     reason = f"Action done by {ctx.author} (ID: {ctx.author.id})"

     if not members:
        members = ctx.guild.members

        prompt = await ctx.prompt("No members were specified, do you want to add the role to all members?")
        if not prompt:
            return await ctx.simple(
                f"Alright, Aborting. If you wish to add the role to limited users, do:\n\n`{ctx.prefix}role @role @user1 @user2 @user3 ...`"
            )

     m = await ctx.simple(f"{emote.Loading} Adding {role.mention} to {plural(members):member|members}.")

     for member in members:
        if role not in member.roles:
            await member.add_roles(role, reason=reason)

     _view = QuotientView(ctx)
     _view.add_item(RoleRevertButton(ctx, role=role, members=members))

     await ctx.safe_delete(m)
     _view.message = await ctx.success(
        f"Added {role.mention} to {plural(members):member|members}.\n\n"
        "```If you cannot see the role in any of the user's profile, just restart your discord app or check audit log.```",
        view=_view,
     )

    @role.command(name="humans", extras={"examples": ["role humans @role", "role humans role_id"]})
    @commands.has_guild_permissions(manage_roles=True)
    @commands.bot_has_guild_permissions(manage_roles=True)
    @commands.cooldown(5, 1, type=commands.BucketType.guild)
    @role_command_check()
    async def role_humans(self, ctx: Context, role: discord.Role):
     """Add a role to all human users."""

     members = [m for m in ctx.guild.members if all([not role in m.roles, not m.bot])]

     prompt = await ctx.prompt(
        title="Are you sure you want to continue?",
        message=f"{role.mention} will be added to all {plural(members):human|humans} in the server.",
     )

     if not prompt:
        return await ctx.success("Alright, Aborting.")

     reason = f"Action done by {ctx.author} (ID: {ctx.author.id})"
     m = await ctx.simple(f"{emote.Loading} Adding {role.mention} to {plural(members):human|humans}.")

     success, failed = 0, 0

     for member in members:
        try:
            await member.add_roles(role, reason=reason)
            success += 1
        except discord.HTTPException:
            failed += 1

     _view = QuotientView(ctx)
     _view.add_item(RoleRevertButton(ctx, role=role, members=members))

     await ctx.safe_delete(m)
     _view.message = await ctx.success(
        f"Successfully added {role.mention} to {plural(success):human|humans}. (Failed: {failed})", view=_view
     )

    @role.command(name="bots", extras={"examples": ["role bots @role", "role bots role_id"]})
    @commands.has_guild_permissions(manage_roles=True)
    @commands.bot_has_guild_permissions(manage_roles=True)
    @role_command_check()
    async def role_bots(self, ctx: Context, role: discord.Role):
     """Add a role to all bot users."""
     members = [m for m in ctx.guild.members if all([not role in m.roles, m.bot])]

     prompt = await ctx.prompt(
        title="Are you sure you want to continue?",
        message=f"{role.mention} will be added to all {plural(members):bot|bots} in the server.",
     )

     if not prompt:
        return await ctx.success("Alright, Aborting.")

     reason = f"Action done by {ctx.author} (ID: {ctx.author.id})"
     m = await ctx.simple(f"{emote.Loading} Adding {role.mention} to {plural(members):bot|bots}.")

     success, failed = 0, 0

     for member in members:
        try:
            await member.add_roles(role, reason=reason)
            success += 1
        except discord.HTTPException:
            failed += 1

     _view = QuotientView(ctx)
     _view.add_item(RoleRevertButton(ctx, role=role, members=members))

     await ctx.safe_delete(m)
     _view.message = await ctx.success(
        f"Successfully added {role.mention} to {plural(success):bot|bots}. (Failed: {failed})", view=_view
     )

    @role.command(name="all", extras={"examples": ["role all @role", "role all role_id"]})
    @commands.has_guild_permissions(manage_roles=True)
    @commands.bot_has_guild_permissions(manage_roles=True)
    @role_command_check()
    async def role_all(self, ctx: Context, role: discord.Role):
     """Add a role to everyone on the server"""

     members = [m for m in ctx.guild.members if not role in m.roles]

     prompt = await ctx.prompt(
        title="Are you sure you want to continue?",
        message=f"{role.mention} will be added to all {plural(members):user|users} in the server.",
     )

     if not prompt:
        return await ctx.success("Alright, Aborting.")

     reason = f"Action done by {ctx.author} (ID: {ctx.author.id})"
     m = await ctx.simple(f"{emote.Loading} Adding {role.mention} to {plural(members):user|users}.")

     success, failed = 0, 0

     for member in members:
        try:
            await member.add_roles(role, reason=reason)
            success += 1
        except discord.HTTPException:
            failed += 1

     _view = QuotientView(ctx)
     _view.add_item(RoleRevertButton(ctx, role=role, members=members))

     await ctx.safe_delete(m)
     _view.message = await ctx.success(
        f"Successfully added {role.mention} to {plural(success):user|users}. (Failed: {failed})", view=_view
     )

    @commands.group(invoke_without_command=True, aliases=["removerole", "takerole"])
    @commands.has_guild_permissions(manage_roles=True)
    @commands.bot_has_guild_permissions(manage_roles=True)
    async def rrole(self, ctx: Context, *args):
     """
     Remove a role from one or multiple users.
     Usage: rrole @role @user1 @user2 OR rrole @user1 @user2 @role
     """
    
     if not args:
        return await ctx.error("Please provide a role and at least one member.")
    
     # Separate roles and members from arguments
     roles = []
     members = []
    
     for arg in args:
        try:
            # Try to convert to role
            role_conv = await commands.RoleConverter().convert(ctx, str(arg))
            roles.append(role_conv)
        except:
            try:
                # Try to convert to member
                member_conv = await commands.MemberConverter().convert(ctx, str(arg))
                members.append(member_conv)
            except:
                pass
    
     # Validate we have exactly one role
     if len(roles) == 0:
        return await ctx.error("Please specify a role to remove.")
     elif len(roles) > 1:
        return await ctx.error("Please specify only one role.")
    
     role = roles[0]
    
     # Manual role checks (since we can't use the decorator)
     if role.managed:
        return await ctx.error(f"{role.mention} is a managed role (bot/integration role) and cannot be assigned manually.")
    
     if role.is_bot_managed():
        return await ctx.error(f"{role.mention} is managed by a bot and cannot be assigned manually.")
    
     if role.is_integration():
        return await ctx.error(f"{role.mention} is an integration role and cannot be assigned manually.")
    
     if role >= ctx.guild.me.top_role:
        return await ctx.error(f"{role.mention} is higher than or equal to my highest role. Please move my role above it.")
    
     if role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
        return await ctx.error(f"{role.mention} is higher than or equal to your highest role.")
    
     reason = f"Action done by {ctx.author} (ID: {ctx.author.id})"
    
     if not members:
        members = [m for m in ctx.guild.members if role in m.roles]

        prompt = await ctx.prompt("No members were specified, do you want to remove the role from all members?")
        if not prompt:
            return await ctx.simple(
                f"Alright, Aborting. If you wish to remove the role from limited users, do:\n\n`{ctx.prefix}rrole @role @user1 @user2 @user3 ...`"
            )

     m = await ctx.simple(f"{emote.Loading} Removing {role.mention} from {plural(members):member|members}.")
 
     for member in members:
        await member.remove_roles(role, reason=reason)

     _view = QuotientView(ctx)
     _view.add_item(RoleRevertButton(ctx, role=role, members=members, take_role=False))

     await ctx.safe_delete(m)
     _view.message = await ctx.success(
        f"Removed {role.mention} from {plural(members):member|members}.",
        view=_view,
     )

    @rrole.command(name="humans")
    @commands.has_guild_permissions(manage_roles=True)
    @commands.bot_has_guild_permissions(manage_roles=True)
    @role_command_check()
    async def rrole_humans(self, ctx: Context, role: discord.Role):
     """Remove a role from all human users."""

     members = [m for m in ctx.guild.members if all([role in m.roles, not m.bot])]

     prompt = await ctx.prompt(
        title="Are you sure you want to continue?",
        message=f"{role.mention} will be removed from all {plural(members):human|humans} in the server.",
     )

     if not prompt:
        return await ctx.success("Alright, Aborting.")

     reason = f"Action done by {ctx.author} (ID: {ctx.author.id})"
     m = await ctx.simple(f"{emote.Loading} Remove {role.mention} from {plural(members):human|humans}.")

     success, failed = 0, 0

     for member in members:
        try:
            await member.remove_roles(role, reason=reason)
            success += 1
        except discord.HTTPException:
            failed += 1

     _view = QuotientView(ctx)
     _view.add_item(RoleRevertButton(ctx, role=role, members=members, take_role=False))

     await ctx.safe_delete(m)
     _view.message = await ctx.success(
        f"Successfully removed {role.mention} from {plural(success):human|humans}. (Failed: {failed})", view=_view
     )

    @rrole.command(name="bots")
    @commands.has_guild_permissions(manage_roles=True)
    @commands.bot_has_guild_permissions(manage_roles=True)
    @role_command_check()
    async def rrole_bots(self, ctx: Context, role: discord.Role):
     """Remove a role from all the bots."""
     members = [m for m in ctx.guild.members if all([role in m.roles, m.bot])]

     prompt = await ctx.prompt(
        title="Are you sure you want to continue?",
        message=f"{role.mention} will be removed from all {plural(members):bot|bots} in the server.",
     )

     if not prompt:
        return await ctx.success("Alright, Aborting.")

     reason = f"Action done by {ctx.author} (ID: {ctx.author.id})"
     m = await ctx.simple(f"{emote.Loading} Remove {role.mention} from {plural(members):bot|bots}.")

     success, failed = 0, 0

     for member in members:
        try:
            await member.remove_roles(role, reason=reason)
            success += 1
        except discord.HTTPException:
            failed += 1

     _view = QuotientView(ctx)
     _view.add_item(RoleRevertButton(ctx, role=role, members=members, take_role=False))

     await ctx.safe_delete(m)
     _view.message = await ctx.success(
         f"Successfully removed {role.mention} from {plural(success):bot|bots}. (Failed: {failed})", view=_view
     )

    @rrole.command(name="all")
    @commands.has_guild_permissions(manage_roles=True)
    @commands.bot_has_guild_permissions(manage_roles=True)
    @role_command_check()
    async def rrole_all(self, ctx: Context, role: discord.Role):
     """Remove a role from everyone on the server."""
     members = [m for m in ctx.guild.members if role in m.roles]

     prompt = await ctx.prompt(
        title="Are you sure you want to continue?",
        message=f"{role.mention} will be removed from all {plural(members):user|users} in the server.",
     )

     if not prompt:
        return await ctx.success("Alright, Aborting.")

     reason = f"Action done by {ctx.author} (ID: {ctx.author.id})"
     m = await ctx.simple(f"{emote.Loading} Removing {role.mention} from {plural(members):user|users}.")

     success, failed = 0, 0

     for member in members:
        try:
            await member.remove_roles(role, reason=reason)
            success += 1
        except discord.HTTPException:
            failed += 1

     _view = QuotientView(ctx)
     _view.add_item(RoleRevertButton(ctx, role=role, members=members, take_role=False))

     await ctx.safe_delete(m)
     _view.message = await ctx.success(
        f"Successfully removed {role.mention} from {plural(success):user|users}. (Failed: {failed})", view=_view
     )
     
    @commands.group(invoke_without_command=True, aliases=("lockdown",))
    async def lock(self, ctx: Context, channel: Optional[discord.TextChannel], duration: Optional[FutureTime]):
        """Lock a channel , category or the whole server."""
        channel = channel or ctx.channel
        check = await Lockdown.filter(guild_id=ctx.guild.id, channel_id=channel.id, type=LockType.channel).first()

        if check is not None:
            return await ctx.error(
                f"**{channel}** is already locked.\n\nTime Remaining: {human_timedelta(check.expire_time)}"
            )

        if not channel.permissions_for(ctx.me).manage_channels:
            return await ctx.error(f"I need `manage_channels` permission in **{channel}**")

        if not channel.permissions_for(ctx.author).manage_channels:
            return await ctx.error(f"You need `manage channels` permission in **{channel}** to use this.")

        perms = channel.overwrites_for(ctx.guild.default_role)
        perms.send_messages = False
        await channel.set_permissions(ctx.guild.default_role, overwrite=perms)

        if duration is None:  # we don't want to store if duration is None.
            return await ctx.success(f"Locked down **{channel.name}**")

        await Lockdown.create(
            guild_id=ctx.guild.id,
            type=LockType.channel,
            expire_time=duration.dt,
            channel_id=channel.id,
            author_id=ctx.author.id,
        )
        timer = await self.bot.reminders.create_timer(
            duration.dt, "lockdown", _type=LockType.channel.value, channel_id=channel.id
        )
        await ctx.success(f"Locked down **{channel}** for {human_timedelta(duration.dt,source= timer.created)}")

    @lock.command(name="server", aliases=("guild",))
    @commands.bot_has_guild_permissions(manage_channels=True)
    @commands.has_permissions(manage_guild=True)
    async def lock_server(self, ctx, duration: Optional[FutureTime]):
        check = await Lockdown.filter(guild_id=ctx.guild.id, type=LockType.guild).first()
        if check is not None:
            text = f"Server is already locked."
            if check.expire_time:
                text += f"\n\nTime Remaining: {human_timedelta(check.expire_time)}"
            return await ctx.error(text)

        channels = list(filter(lambda x: x.overwrites_for(ctx.guild.default_role).send_messages, ctx.guild.channels))
        mine = sum(1 for i in filter(lambda x: x.permissions_for(ctx.me).manage_channels, (channels)))
        # len list would use additional memory so : )

        if not (channels):
            return await ctx.error(f"@everyone doesn't have `send_messages` enabled in any channel.")

        if not mine:
            return await ctx.error(
                f"`{sum(1 for i in channels)} channels` have send messages enabled. But unfortunately I don't permission to edit any of them."
            )

        prompt = await ctx.prompt(
            f"`{sum(1 for i in channels)} channels` have send messages enabled for @everyone,\nI have permissions to modify `{mine} channels`.",
            title="Do you want me to continue?",
        )
        if not prompt:
            return await ctx.success(f"Alright, aborting.")

        await ctx.send(f"Kindly wait.. {emote.Loading}", delete_after=3)

        success, failed = [], 0
        reason = f"Action done by -> {str(ctx.author)} ({ctx.author.id})"
        for channel in channels:
            overwrite = channel.overwrites_for(ctx.guild.default_role)
            overwrite.send_messages = False

            try:
                await channel.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason=reason)
                success.append(channel.id)
            except:
                failed += 1
                continue

        await Lockdown.create(
            guild_id=ctx.guild.id,
            type=LockType.guild,
            channel_id=ctx.channel.id,
            author_id=ctx.author.id,
            channel_ids=success,
            expire_time=duration.dt,
        )

        if duration is None:
            return await ctx.success(f"Locked down `{len(success)} channels` (Failed: `{failed}`)")

        timer = await self.bot.reminders.create_timer(
            duration.dt, "lockdown", _type=LockType.guild.value, guild_id=ctx.guild.id
        )
        await ctx.success(
            f"Locked down `{len(success)} channels` (Failed: `{failed}`) for {human_timedelta(duration.dt, source=timer.created)}"
        )

    @commands.group(aliases=("unlockdown",), invoke_without_command=True)
    async def unlock(self, ctx, *, channel: Optional[discord.TextChannel]):
        channel = channel or ctx.channel

        if not channel.permissions_for(ctx.me).manage_channels:
            return await ctx.error(f"I need `manage_channels` permission in **{channel}**")

        if not channel.permissions_for(ctx.author).manage_channels:
            return await ctx.error(f"You need `manage channels` permission in **{channel}** to use this.")

        perms = channel.overwrites_for(ctx.guild.default_role)
        perms.send_messages = True
        await channel.set_permissions(ctx.guild.default_role, overwrite=perms)

        await ctx.success(f"Unlocked **{channel}**")

        await Lockdown.filter(channel_id=channel.id, type=LockType.channel).delete()

    @unlock.command(name="server", aliases=("guild",))
    @commands.has_permissions(manage_guild=True)
    @commands.bot_has_guild_permissions(manage_channels=True)
    async def unlock_guild(self, ctx):
        check = await Lockdown.get_or_none(guild_id=ctx.guild.id, type=LockType.guild).first()
        if not check:
            return await ctx.error(f"The server is not locked.")

        success = 0
        for channel in check.channels:
            if channel is not None and channel.permissions_for(channel.guild.me).manage_channels:
                perms = channel.overwrites_for(channel.guild.default_role)
                perms.send_messages = True
                await channel.set_permissions(
                    channel.guild.default_role, overwrite=perms, reason="Lockdown timer complete!"
                )
                success += 1

        await ctx.success(
            f"Successfully unlocked `{success}` channels. (`{sum(1 for i in check.channels)}` were locked.)"
        )
        await Lockdown.filter(guild_id=ctx.guild.id, type=LockType.guild).delete()

    @commands.group(invoke_without_command=True)
    async def maintenance(self, ctx: Context):
        """Maintenance ON/ OFF for the server."""
        await ctx.send_help(ctx.command)

    @maintenance.command(name="on")
    @commands.has_permissions(administrator=True)
    @commands.bot_has_guild_permissions(manage_channels=True)
    async def maintenace_on(self, ctx: Context, *, role: discord.Role = None):
        """
        Turn ON maintenance mode.
        You can turn on maintenance for a specific role too , the default role is everyone.
        This will hide all the channels where `role` has `read_messages` permission enabled.
        """
        role = role or ctx.guild.default_role
        check = await Lockdown.filter(type=LockType.maintenance, guild_id=ctx.guild.id, role_id=role.id).first()
        if check:
            return await ctx.error(f"The server is already under maintenance for **{role}**")

        channels = list(filter(lambda x: x.overwrites_for(role).read_messages, ctx.guild.channels))
        mine = sum(1 for i in filter(lambda x: x.permissions_for(ctx.me).manage_channels, (channels)))
        # len list would use additional memory so : )

        if not (channels):
            return await ctx.error(f"**{role}** doesn't have `read_messages` enabled in any channel.")

        if not mine:
            return await ctx.error(
                f"`{sum(1 for i in channels)} channels` have read messages enabled. But unfortunately I don't permission to edit any of them."
            )

        prompt = await ctx.prompt(
            f"`{sum(1 for i in channels)} channels` have read messages enabled for **{role}**,\nI have permissions to modify `{mine} channels`.",
            title="Do you want me to continue?",
        )
        if not prompt:
            return await ctx.success(f"Alright, aborting.")

        await ctx.send(f"Kindly wait.. {emote.Loading}", delete_after=3)

        success, failed = [], 0
        reason = f"Action done by -> {str(ctx.author)} ({ctx.author.id})"
        for channel in channels:
            overwrite = channel.overwrites_for(role)
            overwrite.read_messages = False

            try:
                await channel.set_permissions(role, overwrite=overwrite, reason=reason)
                success.append(channel.id)
            except:
                failed += 1
                continue

        await ctx.success(f"Updated settings for `{len(success)} channels`.(`{failed}` failed)")
        if success:
            await Lockdown.create(
                guild_id=ctx.guild.id,
                type=LockType.maintenance,
                channel_id=ctx.channel.id,
                author_id=ctx.author.id,
                role_id=role.id,
                channel_ids=success,
            )

        prompt = await ctx.prompt(f"Do you want me to make maintenance channels?")

        if prompt:
            overwrites = {
                role: discord.PermissionOverwrite(read_messages=True, send_messages=True, read_message_history=True),
                ctx.guild.me: discord.PermissionOverwrite(
                    read_messages=True, send_messages=True, read_message_history=True
                ),
            }
            await ctx.guild.create_text_channel("maintenance-chat", overwrites=overwrites, reason=reason)
            await ctx.guild.create_voice_channel("maintenance-vc", overwrites=overwrites, reason=reason)
            await ctx.success(f"Done")

        else:
            await ctx.success(f"Ok! Aborting")

    @maintenance.command(name="off")
    @commands.bot_has_guild_permissions(manage_channels=True)
    @commands.has_permissions(administrator=True)
    async def maintenance_off(self, ctx: Context, *, role: discord.Role = None):
        """
        Turn OFF maintenance mode.
        If you turned ON maintenance mode for a specific role , you need to mention it here too.
        """
        role = role or ctx.guild.default_role

        check = await Lockdown.filter(type=LockType.maintenance, guild_id=ctx.guild.id, role_id=role.id).first()
        if not check:
            return await ctx.error(f"The server not under maintenance for **{role}**")

        success = 0
        for channel in check.channels:
            if channel is not None and channel.permissions_for(channel.guild.me).manage_channels:
                perms = channel.overwrites_for(role)
                perms.read_messages = True
                await channel.set_permissions(role, overwrite=perms, reason="Lockdown timer complete!")
                success += 1

        await ctx.success(
            f"Successfully changed settings for `{success}` channels. (`{sum(1 for i in check.channels)}` were hidden.)"
        )

        await Lockdown.filter(type=LockType.maintenance, guild_id=ctx.guild.id, role_id=role.id).delete()

        tc = discord.utils.get(ctx.guild.channels, name="maintenance-chat")
        vc = discord.utils.get(ctx.guild.channels, name="maintenance-vc")

        if tc and vc:
            prompt = await ctx.prompt(message=f"Do you want me to delete maintenance channels?")
            if prompt:
                await tc.delete()
                await vc.delete()
                await ctx.success(f"Success")
            else:
                await ctx.success(f"OK!")



async def setup(bot: Quotient) -> None:
    await bot.add_cog(Mod(bot))
    await bot.add_cog(LockEvents(bot))
    await bot.add_cog(RoleEvents(bot))
