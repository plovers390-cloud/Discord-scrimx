"""
Timed Role Waiting System - Production Ready with Premium
--------------------------
Commands:
- waiting setup (interactive)
- waiting edit <id> (edit existing config)
- waiting list
- waiting delete <id>
- waiting clear
- waiting takeback <id> (remove roles from all users)
- waiting takebackall (remove roles from ALL configs)

Features:
- First come first serve based on message order
- Auto lock channel when user limit reached
- DM users who already have role
- Tag winners and losers at the end
- Auto remove roles during daily reset
- Fixed InvalidStateError with task locks
- Premium: Free users = 2 waitings, Premium = Unlimited
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core import Quotient

import asyncio
from datetime import datetime, time as dt_time, timedelta
from discord.ext import commands, tasks
import discord

from core import Cog, Context
from models import Timer, RoleWaiting, Guild
from utils import emote
import constants as csts


class TimedRoleWaiting(Cog):
    def __init__(self, bot: Quotient):
        self.bot = bot
        self._message_queue = {}  # Store messages per channel for processing
        self._task_lock = asyncio.Lock()  # Prevent race conditions
        self.check_waiting.start()
        self.daily_reset.start()

    def cog_unload(self):
        """Properly cancel tasks on unload"""
        try:
            if self.check_waiting.is_running():
                self.check_waiting.cancel()
        except Exception:
            pass
        
        try:
            if self.daily_reset.is_running():
                self.daily_reset.cancel()
        except Exception:
            pass

    @tasks.loop(seconds=60)
    async def check_waiting(self):
        """Check if any waiting needs to be activated"""
        async with self._task_lock:
            try:
                now = datetime.now(tz=csts.IST)
                current_date = now.date()
                current_hour = now.hour
                current_minute = now.minute
                
                # Get all active waiting configs
                waitings = await RoleWaiting.filter(is_active=True).all()
                
                for waiting in waitings:
                    try:
                        trigger_hour, trigger_minute = map(int, waiting.trigger_time.split(":"))
                    except Exception:
                        continue
                    
                    # Check if time matches
                    time_matches = (current_hour == trigger_hour and current_minute == trigger_minute)
                    already_triggered = (waiting.last_triggered == current_date)
                    
                    # Skip if already triggered today
                    if already_triggered:
                        continue
                    
                    # Trigger if time matches
                    if time_matches:
                        try:
                            await self.activate_waiting(waiting, current_date)
                        except Exception:
                            pass
                            
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

    @tasks.loop(hours=1)
    async def daily_reset(self):
        """Reset all waiting lists at 4:00 AM IST daily"""
        async with self._task_lock:
            try:
                now = datetime.now(tz=csts.IST)
                
                # Check if it's 4:00 AM (with 5 minute window)
                if now.hour == 4 and now.minute < 5:
                    # Reset all waiting configs
                    waitings = await RoleWaiting.filter(is_active=True).all()
                    
                    for waiting in waitings:
                        try:
                            guild = self.bot.get_guild(waiting.guild_id)
                            if not guild:
                                continue
                            
                            role = guild.get_role(waiting.role_id)
                            channel = guild.get_channel(waiting.channel_id)
                            
                            # Remove role from all users who got it
                            if role and waiting.given_users:
                                for user_id in waiting.given_users:
                                    try:
                                        member = guild.get_member(user_id)
                                        if member and role in member.roles:
                                            await member.remove_roles(role, reason="Daily Reset - 4:00 AM IST")
                                    except Exception:
                                        pass
                            
                            # Reset database
                            waiting.given_users = []
                            waiting.last_triggered = None
                            await waiting.save()
                            
                            # Lock channel
                            if channel:
                                try:
                                    await channel.set_permissions(
                                        guild.default_role,
                                        send_messages=False,
                                        view_channel=True,
                                        reason="Daily Reset - 4:00 AM IST"
                                    )
                                except Exception:
                                    pass
                                    
                        except Exception:
                            pass
                    
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

    @check_waiting.before_loop
    async def before_check_waiting(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(1)  # Prevent race conditions

    @daily_reset.before_loop
    async def before_daily_reset(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(2)  # Prevent race conditions

    @check_waiting.error
    async def check_waiting_error(self, error):
        if isinstance(error, asyncio.CancelledError):
            return
        # Silently ignore to prevent crashes
        pass

    @daily_reset.error
    async def daily_reset_error(self, error):
        if isinstance(error, asyncio.CancelledError):
            return
        # Silently ignore to prevent crashes
        pass

    async def activate_waiting(self, waiting: RoleWaiting, current_date):
        """Activate a waiting by opening channel"""
        guild = self.bot.get_guild(waiting.guild_id)
        if not guild:
            return

        channel = guild.get_channel(waiting.channel_id)
        if not channel:
            return

        role = guild.get_role(waiting.role_id)
        if not role:
            return

        # Reset for new day
        waiting.given_users = []
        waiting.last_triggered = current_date
        await waiting.save()

        # Initialize message queue for this channel
        self._message_queue[channel.id] = []

        # Open channel
        try:
            await channel.set_permissions(
                guild.default_role,
                send_messages=True,
                view_channel=True,
                reason=f"Role Waiting Activated - {waiting.max_users} users limit"
            )
        except Exception:
            return

        # Send announcement
        embed = discord.Embed(
            title=f"{emote.edit} Waiting Channel Opened!",
            description=(
                f"<a:prettyarrowR:1431681727629361222> Role: {role.mention}\n"
                f"<a:prettyarrowR:1431681727629361222> First: {waiting.max_users} users will get the role!\n"
                f"<a:prettyarrowR:1431681727629361222> How to claim: Send any message now!\n"
                f"<a:prettyarrowR:1431681727629361222> Be quick! First come first serve!"
            ),
            color=discord.Color.gold(),
            timestamp=datetime.now(tz=csts.IST)
        )
        embed.set_footer(text="Quick! Limited spots available")
        
        # Ping based on type
        ping_mention = ""
        if waiting.ping_type == "here":
            ping_mention = "@here"
        elif waiting.ping_type == "everyone":
            ping_mention = "@everyone"
        elif waiting.ping_type == "role" and waiting.ping_role_id:
            ping_role_obj = guild.get_role(waiting.ping_role_id)
            if ping_role_obj:
                ping_mention = ping_role_obj.mention
        
        try:
            if ping_mention:
                await channel.send(ping_mention, embed=embed)
            else:
                await channel.send(embed=embed)
        except Exception:
            pass

    @commands.group(name="waiting", aliases=["wait"], invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    @commands.bot_has_permissions(manage_channels=True, manage_roles=True)
    async def waiting(self, ctx: Context):
        """Setup timed role waiting system in your server"""
        await ctx.send_help(ctx.command)

    @waiting.command(name="setup", aliases=["add"])
    @commands.has_permissions(manage_guild=True)
    async def wait_setup(self, ctx: Context):
        """Interactive setup for timed role waiting system"""
        
        # Check premium limit
        guild_data = await Guild.get(pk=ctx.guild.id)
        current_count = await RoleWaiting.filter(guild_id=ctx.guild.id).count()
        
        if not guild_data.is_premium:
            if current_count >= 2:
                return await ctx.error(
                    f"{emote.error} **Free Limit Reached!**\n"
                    f"Free users can only create **2 waiting configs**.\n"
                    f"You currently have **{current_count}/2** configs.\n"
                    f"{emote.diamond} Upgrade to **Premium** for unlimited waiting configs!\n"
                    f"Use `{ctx.prefix}premium` to learn more."
                )
        
        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel
        
        # Step 1: Channel
        await ctx.send(
            embed=discord.Embed(
                title=f"{emote.edit} Mention Channel!",
                description=f"Tag the channel where you want to setup waiting IDP.\nExample: #waiting-channel",
                color=self.bot.color
            )
        )
        
        try:
            msg = await self.bot.wait_for('message', check=check, timeout=60.0)
            channel = await commands.TextChannelConverter().convert(ctx, msg.content)
        except asyncio.TimeoutError:
            return await ctx.error(f"{emote.error} Timeout! Setup cancelled.")
        except:
            return await ctx.error(f"{emote.error} Invalid channel! Please mention a valid channel.")
        
        # Step 2: Time
        await ctx.send(
            embed=discord.Embed(
                title=f"{emote.edit} Mention Time!",
                description=(
                    f"Enter the time when channel should open (24-hour format)\n\n"
                    f"Format: `HH:MM`\n"
                    f"Example: `13:57` for 1:57 PM\n"
                    f"Example: `14:30` for 2:30 PM"
                ),
                color=self.bot.color
            )
        )
        
        try:
            msg = await self.bot.wait_for('message', check=check, timeout=60.0)
            time_str = msg.content.strip()
            hour, minute = map(int, time_str.split(":"))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
            trigger_time_str = f"{hour:02d}:{minute:02d}"
        except asyncio.TimeoutError:
            return await ctx.error(f"{emote.error} Timeout! Setup cancelled.")
        except:
            return await ctx.error(f"{emote.error} Invalid time format! Use `HH:MM`")
        
        # Step 3: Role
        await ctx.send(
            embed=discord.Embed(
                title=f"{emote.edit} Mention Role!",
                description=f"Mention the role that should be given to users.\nExample: @1PM IDP Role",
                color=self.bot.color
            )
        )
        
        try:
            msg = await self.bot.wait_for('message', check=check, timeout=60.0)
            role = await commands.RoleConverter().convert(ctx, msg.content)
        except asyncio.TimeoutError:
            return await ctx.error(f"{emote.error} Timeout! Setup cancelled.")
        except:
            return await ctx.error(f"{emote.error} Invalid role! Please mention a valid role.")
        
        if role >= ctx.guild.me.top_role:
            return await ctx.error(f"{emote.error} {role.mention} is higher than my highest role!")
        
        if role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
            return await ctx.error(f"{emote.error} {role.mention} is higher than your highest role!")
        
        # Step 4: User limit
        await ctx.send(
            embed=discord.Embed(
                title=f"{emote.edit} Type User No!",
                description=(
                    f"Enter the user limit (how many users should get the role)\n"
                    f"Enter a number between 1 and 1000\n"
                    f"Example: `50` for 50 users"
                ),
                color=self.bot.color
            )
        )
        
        try:
            msg = await self.bot.wait_for('message', check=check, timeout=60.0)
            user_limit = int(msg.content.strip())
            if user_limit < 1 or user_limit > 1000:
                raise ValueError
        except asyncio.TimeoutError:
            return await ctx.error(f"{emote.error} Timeout! Setup cancelled.")
        except:
            return await ctx.error(f"{emote.error} Invalid number! Enter between 1 and 1000.")
        
        # Step 5: Ping type
        await ctx.send(
            embed=discord.Embed(
                title=f"{emote.edit} Tag Role Pinged",
                description=(
                    f"Which role should be pinged when channel opens?\n\n"
                    f"Options:\n"
                    f"• Type `here` for @here ping\n"
                    f"• Type `everyone` for @everyone ping\n"
                    f"• Mention a role (e.g., @Members)\n"
                    f"• Type `none` for no ping"
                ),
                color=self.bot.color
            )
        )
        
        ping_role_id = None
        ping_type = "here"
        
        try:
            msg = await self.bot.wait_for('message', check=check, timeout=60.0)
            ping_input = msg.content.strip().lower()
            
            if ping_input == "here":
                ping_type = "here"
            elif ping_input == "everyone":
                ping_type = "everyone"
            elif ping_input == "none":
                ping_type = "none"
            else:
                try:
                    ping_role = await commands.RoleConverter().convert(ctx, msg.content)
                    ping_role_id = ping_role.id
                    ping_type = "role"
                except:
                    return await ctx.error(f"{emote.error} Invalid input! Use: `here`, `everyone`, `none`, or mention a role")
        except asyncio.TimeoutError:
            ping_type = "here"
            await ctx.send(f"{emote.info} No response - defaulting to `@here` ping")
        
        # Lock channel initially
        try:
            await channel.set_permissions(
                ctx.guild.default_role,
                send_messages=False,
                view_channel=True,
                reason=f"Role Waiting Setup by {ctx.author}"
            )
        except Exception as e:
            return await ctx.error(f"{emote.error} Failed to lock channel! Make sure I have proper permissions.")
        
        # Create waiting entry
        waiting = await RoleWaiting.create(
            guild_id=ctx.guild.id,
            channel_id=channel.id,
            role_id=role.id,
            trigger_time=trigger_time_str,
            max_users=user_limit,
            ping_role_id=ping_role_id,
            ping_type=ping_type
        )
        
        # Check timing
        now = datetime.now(tz=csts.IST)
        trigger_hour, trigger_minute = map(int, trigger_time_str.split(":"))
        trigger_time_today = now.replace(hour=trigger_hour, minute=trigger_minute, second=0, microsecond=0)
        
        time_status = ""
        if now >= trigger_time_today:
            time_status = f"\n{emote.yellow}**Note:** This time has already passed today. Channel will open tomorrow at `{trigger_time_str}`"
        else:
            time_diff = trigger_time_today - now
            minutes = int(time_diff.total_seconds() / 60)
            time_status = f"\n<a:prettyarrowR:1431681727629361222>Channel will open in approximately {minutes} minutes!"
        
        # Format ping info
        ping_info = ""
        if ping_type == "here":
            ping_info = "@here"
        elif ping_type == "everyone":
            ping_info = "@everyone"
        elif ping_type == "none":
            ping_info = "No ping"
        elif ping_type == "role" and ping_role_id:
            ping_role_obj = ctx.guild.get_role(ping_role_id)
            ping_info = ping_role_obj.mention if ping_role_obj else "Role"
        
        premium_note = ""
        if not guild_data.is_premium:
            remaining = 2 - (current_count + 1)
            premium_note = f"\n{emote.info} Free: {remaining}/2 waiting slots remaining"
        
        embed = discord.Embed(
            title=f"{emote.edit} Role Waiting Setup Complete!",
            description=(
                f"<a:prettyarrowR:1431681727629361222> Channel: {channel.mention}\n"
                f"<a:prettyarrowR:1431681727629361222> Daily Time: `{trigger_time_str}` (24-hour format)\n"
                f"<a:prettyarrowR:1431681727629361222> Role: {role.mention}\n"
                f"<a:prettyarrowR:1431681727629361222> User Limit: {user_limit}\n"
                f"<a:prettyarrowR:1431681727629361222> Ping: {ping_info}\n"
                f"<a:prettyarrowR:1431681727629361222> ID: `{waiting.id}`\n"
                f"<a:prettyarrowR:1431681727629361222> Auto Reset: 4:00 AM IST daily\n"
                f"<a:prettyarrowR:1431681727629361222> Roles will be removed during reset!"
                f"{time_status}{premium_note}"
            ),
            color=discord.Color.green()
        )
        embed.set_footer(text="Channel will automatically open daily • Roles auto-removed at 4 AM")
        
        await ctx.send(embed=embed)

    @waiting.command(name="edit", aliases=["update", "modify"])
    @commands.has_permissions(manage_guild=True)
    async def wait_edit(self, ctx: Context, waiting_id: int):
        """Edit an existing waiting config"""
        
        waiting = await RoleWaiting.filter(id=waiting_id, guild_id=ctx.guild.id).first()
        if not waiting:
            return await ctx.error(f"No waiting config found with ID `{waiting_id}`!")
        
        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel
        
        # Show current config
        channel = ctx.guild.get_channel(waiting.channel_id)
        role = ctx.guild.get_role(waiting.role_id)
        
        current_embed = discord.Embed(
            title=f"{emote.edit} Current Configuration (ID: {waiting_id})",
            description=(
                f"<a:prettyarrowR:1431681727629361222> Channel: {channel.mention if channel else 'Deleted'}\n"
                f"<a:prettyarrowR:1431681727629361222> Time: `{waiting.trigger_time}`\n"
                f"<a:prettyarrowR:1431681727629361222> Role: {role.mention if role else 'Deleted'}\n"
                f"<a:prettyarrowR:1431681727629361222> User Limit: {waiting.max_users}\n"
                f"<a:prettyarrowR:1431681727629361222> Ping Type: {waiting.ping_type}"
            ),
            color=self.bot.color
        )
        await ctx.send(embed=current_embed)
        
        # Ask what to edit
        await ctx.send(
            embed=discord.Embed(
                title=f"{emote.edit} What do you want to edit?",
                description=(
                    f"Type one of the following:\n"
                    f"• `channel` - Change the channel\n"
                    f"• `time` - Change the trigger time\n"
                    f"• `role` - Change the role\n"
                    f"• `limit` - Change user limit\n"
                    f"• `ping` - Change ping settings\n"
                    f"• `cancel` - Cancel editing"
                ),
                color=self.bot.color
            )
        )
        
        try:
            msg = await self.bot.wait_for('message', check=check, timeout=60.0)
            edit_choice = msg.content.strip().lower()
        except asyncio.TimeoutError:
            return await ctx.error(f"{emote.error} Timeout! Edit cancelled.")
        
        if edit_choice == "cancel":
            return await ctx.success("Edit cancelled!")
        
        # Edit channel
        if edit_choice == "channel":
            await ctx.send(f"{emote.edit} Mention the new channel:")
            try:
                msg = await self.bot.wait_for('message', check=check, timeout=60.0)
                new_channel = await commands.TextChannelConverter().convert(ctx, msg.content)
                waiting.channel_id = new_channel.id
                await waiting.save()
                return await ctx.success(f"Updated channel to {new_channel.mention}!")
            except asyncio.TimeoutError:
                return await ctx.error(f"{emote.error} Timeout!")
            except:
                return await ctx.error(f"{emote.error} Invalid channel!")
        
        # Edit time
        elif edit_choice == "time":
            await ctx.send(f"{emote.edit} Enter new time (HH:MM format):")
            try:
                msg = await self.bot.wait_for('message', check=check, timeout=60.0)
                time_str = msg.content.strip()
                hour, minute = map(int, time_str.split(":"))
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    raise ValueError
                waiting.trigger_time = f"{hour:02d}:{minute:02d}"
                await waiting.save()
                return await ctx.success(f"Updated time to `{waiting.trigger_time}`!")
            except asyncio.TimeoutError:
                return await ctx.error(f"{emote.error} Timeout!")
            except:
                return await ctx.error(f"{emote.error} Invalid time format! Use HH:MM")
        
        # Edit role
        elif edit_choice == "role":
            await ctx.send(f"{emote.edit} Mention the new role:")
            try:
                msg = await self.bot.wait_for('message', check=check, timeout=60.0)
                new_role = await commands.RoleConverter().convert(ctx, msg.content)
                
                if new_role >= ctx.guild.me.top_role:
                    return await ctx.error(f"{emote.error} That role is higher than my highest role!")
                
                waiting.role_id = new_role.id
                await waiting.save()
                return await ctx.success(f"Updated role to {new_role.mention}!")
            except asyncio.TimeoutError:
                return await ctx.error(f"{emote.error} Timeout!")
            except:
                return await ctx.error(f"{emote.error} Invalid role!")
        
        # Edit limit
        elif edit_choice == "limit":
            await ctx.send(f"{emote.edit} Enter new user limit (1-1000):")
            try:
                msg = await self.bot.wait_for('message', check=check, timeout=60.0)
                new_limit = int(msg.content.strip())
                if new_limit < 1 or new_limit > 1000:
                    raise ValueError
                waiting.max_users = new_limit
                await waiting.save()
                return await ctx.success(f"Updated user limit to `{new_limit}`!")
            except asyncio.TimeoutError:
                return await ctx.error(f"{emote.error} Timeout!")
            except:
                return await ctx.error(f"{emote.error} Invalid number! Enter 1-1000")
        
        # Edit ping
        elif edit_choice == "ping":
            await ctx.send(
                embed=discord.Embed(
                    title=f"{emote.edit} New Ping Settings",
                    description=(
                        f"Type: `here`, `everyone`, `none`, or mention a role"
                    ),
                    color=self.bot.color
                )
            )
            try:
                msg = await self.bot.wait_for('message', check=check, timeout=60.0)
                ping_input = msg.content.strip().lower()
                
                if ping_input == "here":
                    waiting.ping_type = "here"
                    waiting.ping_role_id = None
                elif ping_input == "everyone":
                    waiting.ping_type = "everyone"
                    waiting.ping_role_id = None
                elif ping_input == "none":
                    waiting.ping_type = "none"
                    waiting.ping_role_id = None
                else:
                    try:
                        ping_role = await commands.RoleConverter().convert(ctx, msg.content)
                        waiting.ping_type = "role"
                        waiting.ping_role_id = ping_role.id
                    except:
                        return await ctx.error(f"{emote.error} Invalid input!")
                
                await waiting.save()
                return await ctx.success(f"Updated ping settings to `{waiting.ping_type}`!")
            except asyncio.TimeoutError:
                return await ctx.error(f"{emote.error} Timeout!")
        
        else:
            return await ctx.error(f"{emote.error} Invalid option! Use: channel, time, role, limit, or ping")

    @waiting.command(name="list", aliases=["view", "show"])
    @commands.has_permissions(manage_guild=True)
    async def wait_list(self, ctx: Context):
        """View all active role waiting configs"""
        
        waitings = await RoleWaiting.filter(guild_id=ctx.guild.id, is_active=True).all()

        if not waitings:
            return await ctx.error(f"{emote.error} No active role waiting configs found!")

        # Check premium status
        guild_data = await Guild.get(pk=ctx.guild.id)
        premium_status = f"{'✅ Premium' if guild_data.is_premium else f'⭐ Free ({len(waitings)}/2)'}"

        embed = discord.Embed(
            title=f"{emote.edit} Active Role Waiting Configs",
            description=f"**Status:** {premium_status}\n\n",
            color=self.bot.color
        )

        current_date = datetime.now(tz=csts.IST).date()

        for waiting in waitings:
            channel = ctx.guild.get_channel(waiting.channel_id)
            role = ctx.guild.get_role(waiting.role_id)
            
            given_count = len(waiting.given_users)
            remaining = waiting.max_users - given_count
            
            if waiting.last_triggered == current_date:
                status = "🔴 Already Run Today"
            else:
                status = "🟢 Ready"
            
            ping_info = ""
            if waiting.ping_type == "here":
                ping_info = "@here"
            elif waiting.ping_type == "everyone":
                ping_info = "@everyone"
            elif waiting.ping_type == "none":
                ping_info = "No ping"
            elif waiting.ping_type == "role" and waiting.ping_role_id:
                ping_role_obj = ctx.guild.get_role(waiting.ping_role_id)
                ping_info = ping_role_obj.mention if ping_role_obj else "Deleted Role"

            embed.description += (
                f"\n<a:prettyarrowR:1431681727629361222> ID: `{waiting.id}` {status}\n"
                f"<a:prettyarrowR:1431681727629361222> Channel: {channel.mention if channel else 'Deleted'}\n"
                f"<a:prettyarrowR:1431681727629361222> Role: {role.mention if role else 'Deleted'}\n"
                f"<a:prettyarrowR:1431681727629361222> Daily Time: `{waiting.trigger_time}` IST\n"
                f"<a:prettyarrowR:1431681727629361222> Ping: {ping_info}\n"
                f"<a:prettyarrowR:1431681727629361222> User Limit: {waiting.max_users}\n"
                f"<a:prettyarrowR:1431681727629361222> Given Today: {given_count}/{waiting.max_users} ({remaining} remaining)\n"
                f"─────────────────\n"
            )

        embed.set_footer(text="Auto resets at 4:00 AM IST • Use 'waiting edit <id>' to modify")
        await ctx.send(embed=embed)

    @waiting.command(name="delete", aliases=["remove", "del", "stop"])
    @commands.has_permissions(manage_guild=True)
    async def wait_delete(self, ctx: Context, waiting_id: int):
        """Delete/Stop a role waiting config by ID"""
        
        waiting = await RoleWaiting.filter(id=waiting_id, guild_id=ctx.guild.id).first()

        if not waiting:
            return await ctx.error(f"No waiting config found with ID `{waiting_id}`!")

        await waiting.delete()
        await ctx.success(f"Stopped role waiting config with ID `{waiting_id}`!")

    @waiting.command(name="clear", aliases=["deleteall", "stopall"])
    @commands.has_permissions(manage_guild=True)
    async def wait_clear(self, ctx: Context):
        """Clear/Stop all role waiting configs"""
        
        count = await RoleWaiting.filter(guild_id=ctx.guild.id).count()
        
        if count == 0:
            return await ctx.error(f"{emote.error} No role waiting configs to clear!")

        prompt = await ctx.prompt(f"Are you sure you want to stop all {count} role waiting config(s)?")

        if not prompt:
            return await ctx.success("Cancelled!")

        await RoleWaiting.filter(guild_id=ctx.guild.id).delete()
        await ctx.success(f"Stopped all {count} role waiting config(s)!")

    @waiting.command(name="takeback", aliases=["remove-roles", "reset-roles", "tb"])
    @commands.has_permissions(manage_guild=True)
    async def wait_takeback(self, ctx: Context, waiting_id: int):
        """Remove roles from all users who got them today for a specific waiting config"""
        
        waiting = await RoleWaiting.filter(id=waiting_id, guild_id=ctx.guild.id).first()

        if not waiting:
            return await ctx.error(f"No waiting config found with ID `{waiting_id}`!")
        
        if not waiting.given_users:
            return await ctx.error(f"No users have received roles for this waiting yet!")
        
        role = ctx.guild.get_role(waiting.role_id)
        if not role:
            return await ctx.error(f"Role not found!")
        
        removed_count = 0
        for user_id in waiting.given_users:
            try:
                member = ctx.guild.get_member(user_id)
                if member and role in member.roles:
                    await member.remove_roles(role, reason=f"Takeback by {ctx.author}")
                    removed_count += 1
            except Exception:
                pass
        
        waiting.given_users = []
        await waiting.save()
        
        await ctx.success(f"Removed {role.mention} from {removed_count} user(s)!")

    @waiting.command(name="takebackall", aliases=["remove-all", "reset-all", "tba"])
    @commands.has_permissions(manage_guild=True)
    async def wait_takeback_all(self, ctx: Context):
        """Remove roles from ALL users across ALL waiting configs in your server"""
        
        waitings = await RoleWaiting.filter(guild_id=ctx.guild.id).all()
        
        if not waitings:
            return await ctx.error(f"{emote.error} No waiting configs found in this server!")
        
        # Count total users who have roles
        total_users_with_roles = sum(len(w.given_users) for w in waitings if w.given_users)
        
        if total_users_with_roles == 0:
            return await ctx.error(f"{emote.error} No users have received roles from any waiting configs!")
        
        # Confirmation prompt
        prompt = await ctx.prompt(
            f"{emote.yellow} **WARNING!**\n"
            f"This will remove roles from **{total_users_with_roles} user(s)** across **{len(waitings)} waiting config(s)**!\n\n"
            f"Are you sure you want to proceed?"
        )
        
        if not prompt:
            return await ctx.success("Cancelled!")
        
        # Remove roles from all configs
        total_removed = 0
        configs_processed = 0
        
        for waiting in waitings:
            if not waiting.given_users:
                continue
                
            role = ctx.guild.get_role(waiting.role_id)
            if not role:
                continue
            
            for user_id in waiting.given_users:
                try:
                    member = ctx.guild.get_member(user_id)
                    if member and role in member.roles:
                        await member.remove_roles(role, reason=f"Takeback All by {ctx.author}")
                        total_removed += 1
                except Exception:
                    pass
            
            # Reset the waiting config
            waiting.given_users = []
            await waiting.save()
            configs_processed += 1
        
        embed = discord.Embed(
            title=f"{emote.check} Takeback All Completed!",
            description=(
                f"<a:prettyarrowR:1431681727629361222> Removed roles from **{total_removed}** user(s)\n"
                f"<a:prettyarrowR:1431681727629361222> Processed **{configs_processed}** waiting config(s)\n"
                f"<a:prettyarrowR:1431681727629361222> All configs have been reset!"
            ),
            color=discord.Color.green()
        )
        
        await ctx.send(embed=embed)

    @waiting.command(name="test", aliases=["trigger", "force"])
    @commands.has_permissions(administrator=True)
    async def wait_test(self, ctx: Context, waiting_id: int):
        """Manually trigger a waiting (for testing) - Admin only"""
        
        waiting = await RoleWaiting.filter(id=waiting_id, guild_id=ctx.guild.id).first()

        if not waiting:
            return await ctx.error(f"{emote.error} No waiting config found with ID `{waiting_id}`!")

        current_date = datetime.now(tz=csts.IST).date()
        await self.activate_waiting(waiting, current_date)
        await ctx.success(f"Manually triggered waiting config ID `{waiting_id}`!")

    @Cog.listener()
    async def on_message(self, message: discord.Message):
        """Process messages in waiting channels - First come first serve"""
        
        if not message.guild or message.author.bot:
            return

        # Check if message is in an active waiting channel
        waitings = await RoleWaiting.filter(
            guild_id=message.guild.id,
            channel_id=message.channel.id,
            is_active=True
        ).all()

        if not waitings:
            return

        current_date = datetime.now(tz=csts.IST).date()

        for waiting in waitings:
            # Check if waiting has been triggered today
            if waiting.last_triggered != current_date:
                continue

            role = message.guild.get_role(waiting.role_id)
            if not role:
                continue

            # Check if user already has the role - DM them
            if role in message.author.roles:
                try:
                    await message.author.send(
                        f"{emote.info} Hey {message.author.mention}, you already have the {role.name} role in **{message.guild.name}**!"
                    )
                except:
                    pass
                continue

            # Check if user already got role today
            if message.author.id in waiting.given_users:
                continue

            # Add to message queue
            if message.channel.id not in self._message_queue:
                self._message_queue[message.channel.id] = []
            
            self._message_queue[message.channel.id].append((message.author, message.created_at))

            # Check if we've reached the limit
            if len(self._message_queue[message.channel.id]) >= waiting.max_users:
                # Lock channel immediately
                try:
                    await message.channel.set_permissions(
                        message.guild.default_role,
                        send_messages=False,
                        reason="Role Waiting - Limit reached"
                    )
                except:
                    pass

                # Sort by timestamp (first come first serve)
                self._message_queue[message.channel.id].sort(key=lambda x: x[1])
                
                # Take only the first max_users
                winners = [author for author, _ in self._message_queue[message.channel.id][:waiting.max_users]]
                all_participants = [author for author, _ in self._message_queue[message.channel.id]]
                losers = [author for author in all_participants if author not in winners]

                # Give roles to winners
                for winner in winners:
                    try:
                        await winner.add_roles(role, reason=f"Role Waiting Winner")
                        waiting.given_users.append(winner.id)
                    except Exception:
                        pass
                
                await waiting.save()

                # Announce results
                winners_mention = " ".join([winner.mention for winner in winners])
                
                winner_embed = discord.Embed(
                    title=f"{emote.edit} Waiting Channel Closed!",
                    description=(
                        f"<a:prettyarrowR:1431681727629361222> **Congrats ({len(winners)} users):**\n"
                        f"{winners_mention}\n\n"
                        f"Congratulations! You all received {role.mention}!"
                    ),
                    color=discord.Color.green()
                )
                await message.channel.send(embed=winner_embed)

                # Tag losers if any
                if losers:
                    losers_mention = " ".join([loser.mention for loser in losers])
                    loser_embed = discord.Embed(
                        title=f"{emote.yellow} Better Luck Next Time!",
                        description=(
                            f"<a:prettyarrowR:1431681727629361222> **Unfortunately, these users didn't make it:**\n"
                            f"{losers_mention}\n\n"
                            f"The channel will reopen tomorrow at `{waiting.trigger_time}`!"
                        ),
                        color=discord.Color.orange()
                    )
                    await message.channel.send(embed=loser_embed)

                # Clear queue
                self._message_queue[message.channel.id] = []


async def setup(bot: Quotient):
    await bot.add_cog(TimedRoleWaiting(bot))