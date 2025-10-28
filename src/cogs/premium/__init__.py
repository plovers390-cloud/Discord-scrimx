from __future__ import annotations

import asyncio
import typing
import random

if typing.TYPE_CHECKING:
    from core import Quotient

from contextlib import suppress
from datetime import datetime, timedelta

import discord
from discord.ext import commands, tasks
from tortoise.expressions import Q

import config
from constants import random_greeting, random_thanks
from core import Cog, Context
from models import Guild, PremiumPlan, PremiumTxn, Timer, User
from utils import IST, discord_timestamp, strtime, checks
from utils import emote

from .expire import deactivate_premium, extra_guild_perks, remind_guild_to_pay, remind_user_to_pay
from .views import PremiumPurchaseBtn, PremiumView


class CustomizationView(discord.ui.View):
    def __init__(self, ctx: Context):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.bot = ctx.bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("This is not for you!", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Change Avatar", style=discord.ButtonStyle.blurple, emoji="🖼️")
    async def change_avatar(self, interaction: discord.Interaction, button: discord.ui.Button):
     await interaction.response.send_message(
        f"{emote.info} Please send the image URL or upload an image for the server avatar.\n"
        f"{emote.yellow} Type `cancel` to cancel this operation.\n"
        f"{emote.yellow} **Note:** This attempts server-specific avatar. May require special bot permissions.",
        ephemeral=True
     )
    
     def check(m):
        return m.author.id == self.ctx.author.id and m.channel.id == self.ctx.channel.id
    
     try:
        msg = await self.bot.wait_for('message', timeout=60.0, check=check)
        
        if msg.content.lower() == 'cancel':
            return await self.ctx.send(f"{emote.xmark} Operation cancelled!")
        
        image_url = None
        if msg.attachments:
            image_url = msg.attachments[0].url
        elif msg.content.startswith(('http://', 'https://')):
            image_url = msg.content
        else:
            return await self.ctx.error("Invalid image URL or attachment!")
        
        async with self.bot.session.get(image_url) as resp:
            if resp.status != 200:
                return await self.ctx.error("Could not download the image!")
            
            image_data = await resp.read()
            
            # Try server-specific avatar using Discord HTTP API
            try:
                guild_id = self.ctx.guild.id
                # Convert image to base64
                import base64
                avatar_b64 = f"data:image/png;base64,{base64.b64encode(image_data).decode('utf-8')}"
                
                # Attempt to set guild member profile avatar via HTTP endpoint
                route = discord.http.Route(
                    'PATCH',
                    f'/guilds/{guild_id}/members/@me',
                )
                payload = {'avatar': avatar_b64}
                
                await self.bot.http.request(route, json=payload)
                await self.ctx.success(f"{emote.check} Server avatar changed successfully!")
                
            except discord.HTTPException as e:
                # Fallback: Change global avatar if server-specific fails
                await self.bot.user.edit(avatar=image_data)
                await self.ctx.send(
                    f"{emote.yellow} Server-specific avatar not supported by Discord for bots.\n"
                    f"{emote.check} Changed global bot avatar instead!"
                )
                
     except asyncio.TimeoutError:
        await self.ctx.error("You took too long to respond!")
     except Exception as e:
        await self.ctx.error(f"Failed to change avatar: {e}")

    @discord.ui.button(label="Change Bio", style=discord.ButtonStyle.blurple, emoji="📝")
    async def change_bio(self, interaction: discord.Interaction, button: discord.ui.Button):
     await interaction.response.send_message(
        f"{emote.info} Please send the new server bio/about me.\n"
        f"{emote.yellow} Type `cancel` to cancel this operation.\n"
        f"{emote.yellow} **Note:** Bio will be set globally (Discord limitation for bots).",
        ephemeral=True
    )
    
     def check(m):
        return m.author.id == self.ctx.author.id and m.channel.id == self.ctx.channel.id
    
     try:
        msg = await self.bot.wait_for('message', timeout=60.0, check=check)
        
        if msg.content.lower() == 'cancel':
            return await self.ctx.send(f"{emote.xmark} Operation cancelled!")
        
        new_bio = msg.content.strip()
        
        if len(new_bio) > 190:
            return await self.ctx.error("Bio must be 190 characters or less!")
        
        # Change bot bio globally (server-specific not supported for bots)
        await self.bot.user.edit(bio=new_bio)
        await self.ctx.success(
            f"{emote.check} Bot bio changed successfully!\n"
            f"**New Bio:** {new_bio}\n"
            f"{emote.yellow} Note: Bio is global for all servers (Discord limitation)"
        )
        
     except asyncio.TimeoutError:
        await self.ctx.error("You took too long to respond!")
     except discord.HTTPException as e:
        await self.ctx.error(f"Failed to change bio: {e}")

    @discord.ui.button(label="Change Banner", style=discord.ButtonStyle.blurple, emoji="🎨")
    async def change_banner(self, interaction: discord.Interaction, button: discord.ui.Button):
     await interaction.response.send_message(
        f"{emote.info} Please send the image URL or upload an image for the server banner.\n"
        f"{emote.yellow} Type `cancel` to cancel this operation.\n"
        f"{emote.yellow} **Note:** This attempts server-specific banner. May require special permissions.",
        ephemeral=True
     )
    
     def check(m):
        return m.author.id == self.ctx.author.id and m.channel.id == self.ctx.channel.id
    
     try:
        msg = await self.bot.wait_for('message', timeout=60.0, check=check)
        
        if msg.content.lower() == 'cancel':
            return await self.ctx.send(f"{emote.xmark} Operation cancelled!")
        
        image_url = None
        if msg.attachments:
            image_url = msg.attachments[0].url
        elif msg.content.startswith(('http://', 'https://')):
            image_url = msg.content
        else:
            return await self.ctx.error("Invalid image URL or attachment!")
        
        async with self.bot.session.get(image_url) as resp:
            if resp.status != 200:
                return await self.ctx.error("Could not download the image!")
            
            image_data = await resp.read()
            
            # Try server-specific banner using Discord HTTP API
            try:
                guild_id = self.ctx.guild.id
                # Convert image to base64
                import base64
                banner_b64 = f"data:image/png;base64,{base64.b64encode(image_data).decode('utf-8')}"
                
                # Attempt to set guild member profile banner via HTTP endpoint
                route = discord.http.Route(
                    'PATCH',
                    f'/guilds/{guild_id}/members/@me',
                )
                payload = {'banner': banner_b64}
                
                await self.bot.http.request(route, json=payload)
                await self.ctx.success(f"{emote.check} Server banner changed successfully!")
                
            except discord.HTTPException as e:
                # Fallback: Change global banner if server-specific fails
                await self.bot.user.edit(banner=image_data)
                await self.ctx.send(
                    f"{emote.yellow} Server-specific banner not supported by Discord for bots.\n"
                    f"{emote.check} Changed global bot banner instead!"
                )
                
     except asyncio.TimeoutError:
        await self.ctx.error("You took too long to respond!")
     except Exception as e:
        await self.ctx.error(f"Failed to change banner: {e}")

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red, emoji="❌")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
     await interaction.response.send_message(f"{emote.check} Customization cancelled!", ephemeral=True)
     self.stop()


class PremiumCog(Cog, name="Premium"):
    def __init__(self, bot: Quotient):
        self.bot = bot
        self.hook = discord.Webhook.from_url(self.bot.config.PUBLIC_LOG, session=self.bot.session)
        self.remind_peeps_to_pay.start()
        self.setup_premium_plans.start()

    # ==================== MANUAL PREMIUM COMMANDS ====================
    
    @commands.command(name="addpremium", aliases=["ap"])
    @commands.is_owner()
    async def add_premium(self, ctx: Context, user: discord.User, days: int = 30):
        """
        Manually add premium to a user and current guild.
        Usage: addpremium @user 30
        """
        try:
            # User premium add karo
            user_obj, created = await User.get_or_create(user_id=user.id)
            
            # Calculate new expiry time
            if user_obj.is_premium and user_obj.premium_expire_time:
                end_time = user_obj.premium_expire_time + timedelta(days=days)
                msg_type = "extended"
            else:
                end_time = datetime.now(IST) + timedelta(days=days)
                msg_type = "added"
            
            # Update user
            await User.filter(pk=user_obj.pk).update(
                is_premium=True,
                premium_expire_time=end_time
            )
            
            # Guild premium bhi add karo
            guild_updated = False
            if ctx.guild:
                guild, _ = await Guild.get_or_create(guild_id=ctx.guild.id)
                
                if guild.is_premium and guild.premium_end_time:
                    guild_end = guild.premium_end_time + timedelta(days=days)
                else:
                    guild_end = datetime.now(IST) + timedelta(days=days)
                
                await Guild.filter(pk=guild.pk).update(
                    is_premium=True,
                    premium_end_time=guild_end,
                    made_premium_by=user.id
                )
                guild_updated = True
            
            # Success embed
            embed = discord.Embed(
                title=f"{emote.crown} Premium {msg_type.title()} Successfully!",
                color=discord.Color.gold(),
                timestamp=datetime.now(IST)
            )
            embed.add_field(name="User", value=user.mention, inline=True)
            embed.add_field(name="Duration", value=f"{days} days", inline=True)
            embed.add_field(name="Expires At", value=discord_timestamp(end_time, 'F'), inline=False)
            
            if guild_updated:
                embed.add_field(name="Guild", value=ctx.guild.name, inline=False)
                embed.add_field(name="Guild Expiry", value=discord_timestamp(guild_end, 'F'), inline=False)
            
            embed.set_footer(text=f"Added by {ctx.author}", icon_url=ctx.author.display_avatar.url)
            embed.set_thumbnail(url=user.display_avatar.url)
            
            await ctx.send(embed=embed)
            
            # Try to DM the user
            try:
                dm_embed = discord.Embed(
                    title=f"{emote.crown} You received Premium!",
                    description=f"You have been granted **{days} days** of ScrimX Premium!\n\nExpires: {discord_timestamp(end_time, 'F')}",
                    color=discord.Color.gold()
                )
                await user.send(embed=dm_embed)
            except:
                pass
                
        except Exception as e:
            await ctx.send(f"{emote.xmark} Error: {str(e)}")

    @commands.command(name="removepremium", aliases=["rp"])
    @commands.is_owner()
    async def remove_premium(self, ctx: Context, *, target: str):
     """
     Remove premium from a user or guild.
     Usage: 
        removepremium @user  (remove user premium)
        removepremium 123456789  (remove guild premium by ID)
     """
     try:
         # Try to convert to user first
         user = None
         try:
            user = await commands.UserConverter().convert(ctx, target)
         except commands.UserNotFound:
            pass
        
         if user:
            # Remove user premium
            user_obj = await User.get_or_none(user_id=user.id)
            
            if not user_obj or not user_obj.is_premium:
                return await ctx.send(f"{emote.xmark} {user.mention} doesn't have premium!")
            
            await User.filter(pk=user_obj.pk).update(
                is_premium=False,
                premium_expire_time=None
            )
            
            embed = discord.Embed(
                title=f"{emote.xmark} User Premium Removed",
                description=f"Premium has been removed from {user.mention}",
                color=discord.Color.red(),
                timestamp=datetime.now(IST)
            )
            embed.set_thumbnail(url=user.display_avatar.url)
            embed.set_footer(text=f"Removed by {ctx.author}")
            
            await ctx.send(embed=embed)
            
            # Try to notify user
            try:
                dm_embed = discord.Embed(
                    title=f"{emote.xmark} Premium Removed",
                    description="Your ScrimX Premium has been removed by the bot owner.",
                    color=discord.Color.red()
                )
                await user.send(embed=dm_embed)
            except:
                pass
            
            return
        
        # If not a user, try as guild ID
         try:
            guild_id = int(target)
         except ValueError:
            return await ctx.send(f"{emote.xmark} Invalid user mention or guild ID!")
        
         guild_obj = await Guild.get_or_none(guild_id=guild_id)
        
         if not guild_obj or not guild_obj.is_premium:
            return await ctx.send(f"{emote.xmark} Guild ID `{guild_id}` doesn't have premium!")
        
         await Guild.filter(pk=guild_obj.pk).update(
            is_premium=False,
            premium_end_time=None,
            made_premium_by=None
        )
        
         guild = self.bot.get_guild(guild_id)
         guild_name = guild.name if guild else f"Guild ID: {guild_id}"
        
         embed = discord.Embed(
            title=f"{emote.xmark} Guild Premium Removed",
            description=f"Premium has been removed from **{guild_name}**",
            color=discord.Color.red(),
            timestamp=datetime.now(IST)
        )
        
         if guild and guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        
         embed.add_field(name="Guild ID", value=f"`{guild_id}`", inline=False)
         embed.set_footer(text=f"Removed by {ctx.author}")
        
         await ctx.send(embed=embed)
            
     except Exception as e:
         await ctx.send(f"{emote.xmark} Error: {str(e)}")


    @commands.command(name="removeguildpremium", aliases=["rgp"])
    @commands.is_owner()
    async def remove_guild_premium(self, ctx: Context, guild_id: int):
     """
     Remove premium from a guild by ID.
     Usage: removeguildpremium 123456789
     """
     try:
         guild_obj = await Guild.get_or_none(guild_id=guild_id)
        
         if not guild_obj or not guild_obj.is_premium:
            return await ctx.send(f"{emote.xmark} Guild ID `{guild_id}` doesn't have premium!")
        
         await Guild.filter(pk=guild_obj.pk).update(
            is_premium=False,
            premium_end_time=None,
            made_premium_by=None
        )
        
         guild = self.bot.get_guild(guild_id)
         guild_name = guild.name if guild else f"Guild ID: {guild_id}"
        
         embed = discord.Embed(
            title=f"{emote.xmark} Guild Premium Removed",
            description=f"Premium has been removed from **{guild_name}**",
            color=discord.Color.red(),
            timestamp=datetime.now(IST)
        )
        
         if guild and guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        
         embed.add_field(name="Guild ID", value=f"`{guild_id}`", inline=False)
         embed.set_footer(text=f"Removed by {ctx.author}")
        
         await ctx.send(embed=embed)
        
     except Exception as e:
        await ctx.send(f"{emote.xmark} Error: {str(e)}")

    @commands.command(name="checkpremium", aliases=["cp"])
    @commands.is_owner()
    async def check_premium(self, ctx: Context, user: discord.User = None):
        """
        Check premium status of a user.
        Usage: checkpremium @user
        """
        try:
            if not user:
                user = ctx.author
            
            user_obj = await User.get_or_none(user_id=user.id)
            
            embed = discord.Embed(
                title=f"Premium Status - {user.name}",
                color=discord.Color.gold() if (user_obj and user_obj.is_premium) else discord.Color.red(),
                timestamp=datetime.now(IST)
            )
            
            embed.set_thumbnail(url=user.display_avatar.url)
            
            if user_obj and user_obj.is_premium:
                embed.add_field(name="Status", value=f"{emote.check} Active", inline=True)
                
                if user_obj.premium_expire_time:
                    embed.add_field(
                        name="Expires At", 
                        value=discord_timestamp(user_obj.premium_expire_time, 'F'),
                        inline=True
                    )
                    
                    days_left = (user_obj.premium_expire_time - datetime.now(IST)).days
                    embed.add_field(name="Days Remaining", value=f"{days_left} days", inline=False)
            else:
                embed.add_field(name="Status", value=f"{emote.xmark} Not Active", inline=False)
            
            # Guild premium status
            if ctx.guild:
                guild = await Guild.get_or_none(guild_id=ctx.guild.id)
                if guild and guild.is_premium:
                    embed.add_field(
                        name="Guild Premium", 
                        value=f"{emote.check} Active until {discord_timestamp(guild.premium_end_time, 'f')}" if guild.premium_end_time else f"{emote.check} Active",
                        inline=False
                    )
                else:
                    embed.add_field(name="Guild Premium", value=f"{emote.xmark} Not Active", inline=False)
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"{emote.xmark} Error: {str(e)}")

    @commands.command(name="addguildpremium", aliases=["agp"])
    @commands.is_owner()
    async def add_guild_premium(self, ctx: Context, guild_id: int, days: int = 30):
        """
        Add premium to any guild by ID.
        Usage: addguildpremium 123456789 30
        """
        try:
            guild, _ = await Guild.get_or_create(guild_id=guild_id)
            
            if guild.is_premium and guild.premium_end_time:
                end_time = guild.premium_end_time + timedelta(days=days)
                msg_type = "extended"
            else:
                end_time = datetime.now(IST) + timedelta(days=days)
                msg_type = "added"
            
            await Guild.filter(pk=guild.pk).update(
                is_premium=True,
                premium_end_time=end_time,
                made_premium_by=ctx.author.id
            )
            
            guild_obj = self.bot.get_guild(guild_id)
            guild_name = guild_obj.name if guild_obj else f"Guild ID: {guild_id}"
            
            embed = discord.Embed(
                title=f"{emote.crown} Guild Premium {msg_type.title()}!",
                color=discord.Color.green(),
                timestamp=datetime.now(IST)
            )
            embed.add_field(name="Guild", value=guild_name, inline=False)
            embed.add_field(name="Duration", value=f"{days} days", inline=True)
            embed.add_field(name="Expires At", value=discord_timestamp(end_time, 'F'), inline=True)
            embed.set_footer(text=f"Added by {ctx.author}")
            
            if guild_obj:
                embed.set_thumbnail(url=guild_obj.icon.url if guild_obj.icon else None)
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"{emote.xmark} Error: {str(e)}")

    @commands.command(name="listpremium", aliases=["lp"])
    @commands.is_owner()
    async def list_premium(self, ctx: Context):
        """
        List all active premium users and guilds.
        Usage: listpremium
        """
        try:
            # Get premium users
            premium_users = await User.filter(is_premium=True).all()
            
            # Get premium guilds
            premium_guilds = await Guild.filter(is_premium=True).all()
            
            embed = discord.Embed(
                title=f"{emote.crown} Active Premium Users & Guilds",
                color=discord.Color.gold(),
                timestamp=datetime.now(IST)
            )
            
            # Users list
            if premium_users:
                user_list = []
                for i, user_obj in enumerate(premium_users[:10], 1):  # Limit to 10
                    user = await self.bot.getch(self.bot.get_user, self.bot.fetch_user, user_obj.user_id)
                    if user:
                        days_left = (user_obj.premium_expire_time - datetime.now(IST)).days if user_obj.premium_expire_time else 0
                        user_list.append(f"`{i}.` {user.mention} - {days_left}d left")
                
                embed.add_field(
                    name=f"👥 Premium Users ({len(premium_users)})", 
                    value="\n".join(user_list) if user_list else "None",
                    inline=False
                )
            
            # Guilds list
            if premium_guilds:
                guild_list = []
                for i, guild_obj in enumerate(premium_guilds[:10], 1):  # Limit to 10
                    guild = self.bot.get_guild(guild_obj.guild_id)
                    if guild:
                        days_left = (guild_obj.premium_end_time - datetime.now(IST)).days if guild_obj.premium_end_time else 0
                        guild_list.append(f"`{i}.` {guild.name} - {days_left}d left")
                
                embed.add_field(
                    name=f"🏰 Premium Guilds ({len(premium_guilds)})", 
                    value="\n".join(guild_list) if guild_list else "None",
                    inline=False
                )
            
            if not premium_users and not premium_guilds:
                embed.description = f"{emote.xmark} No active premium users or guilds found."
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"{emote.xmark} Error: {str(e)}")

    # ==================== END MANUAL PREMIUM COMMANDS ====================

    @tasks.loop(count=1)
    async def setup_premium_plans(self):
        """Auto-setup premium plans on bot startup"""
        await self.bot.wait_until_ready()
        
        try:
            plans_count = await PremiumPlan.all().count()
            
            if plans_count == 0:
                print("📦 No premium plans found. Inserting default plans...")
                await PremiumPlan.insert_plans()
                print("✅ Premium plans inserted successfully!")
                
                plans = await PremiumPlan.all()
                for plan in plans:
                    print(f"  ├─ {plan.name} - ₹{plan.price}")
            else:
                print(f"✅ Premium plans already configured ({plans_count} plans)")
                
        except Exception as e:
            print(f"❌ Error setting up premium plans: {e}")

    @commands.command()
    @commands.has_permissions(manage_guild=True)
    @checks.is_premium_guild()
    async def custom(self, ctx: Context):
     """
     Customize bot's appearance (Avatar, Bio, Banner) for this server.
     This is a premium-only feature.
     """
     embed = discord.Embed(
        color=self.bot.color,
        title=f"{emote.crown} Bot Customization Panel",
        description=(
            f"{emote.check} Use the buttons below to customize your bot for this server!\n\n"
            f"{emote.info} **Available Options:**\n"
            f"🖼️ **Change Avatar** - Update bot's avatar (Global)\n"
            f"📝 **Change Bio** - Update bot's bio (Global)\n"
            f"🎨 **Change Banner** - Update bot's banner (Global)\n\n"
            f"{emote.edit} **Note:** Only users with Manage Server permission can use this."        
        )
     )
     embed.set_thumbnail(url=self.bot.user.display_avatar.url)
     embed.set_footer(text="ScrimX Premium Feature")
    
     view = CustomizationView(ctx)
     await ctx.send(embed=embed, view=view)

    @commands.group(invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def welcome(self, ctx: Context):
        """
        Welcome system commands.
        Use subcommands to setup or test welcome messages.
        """
        embed = discord.Embed(
            color=self.bot.color,
            title=f"{emote.info} Welcome System",
            description=(
                f"**Available Commands:**\n\n"
                f"`{ctx.prefix}welcome setup <#channel>` - Set welcome channel\n"
                f"`{ctx.prefix}welcome banner` - Set custom welcome banner/GIF\n"
                f"`{ctx.prefix}welcome test [@member]` - Test welcome message\n"
                f"`{ctx.prefix}welcome disable` - Disable welcome system\n"
                f"`{ctx.prefix}welcome status` - Check welcome system status\n"
            )
        )
        await ctx.send(embed=embed)

    @welcome.command(name="setup")
    @commands.has_permissions(administrator=True)
    async def welcome_setup(self, ctx: Context, channel: discord.TextChannel):
        """
        Setup welcome channel for the server.
        Usage: xwelcome setup #channel
        """
        await Guild.filter(guild_id=ctx.guild.id).update(welcome_channel=channel.id)
        
        if ctx.guild.id in self.bot.cache.guild_data:
            self.bot.cache.guild_data[ctx.guild.id]["welcome_channel"] = channel.id
        
        embed = discord.Embed(
            color=discord.Color.green(),
            description=f"{emote.check} Welcome channel set to {channel.mention}\n\nNew members will be welcomed there automatically!"
        )
        await ctx.send(embed=embed)

    @welcome.command(name="banner")
    @commands.has_permissions(administrator=True)
    async def welcome_banner(self, ctx: Context):
        """
        Set custom welcome banner/GIF for the server.
        Usage: xwelcome banner
        """
        embed = discord.Embed(
            color=self.bot.color,
            title=f"{emote.info} Set Welcome Banner",
            description=(
                f"Please send your custom banner/GIF:\n\n"
                f"{emote.check} Upload an image/GIF\n"
                f"{emote.check} Or send an image/GIF URL\n\n"
                f"{emote.yellow} Type `cancel` to cancel this operation.\n"
                f"{emote.yellow} Type `reset` to use default banners."
            )
        )
        await ctx.send(embed=embed)
        
        def check(m):
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id
        
        try:
            msg = await self.bot.wait_for('message', timeout=60.0, check=check)
            
            if msg.content.lower() == 'cancel':
                return await ctx.send(f"{emote.xmark} Operation cancelled!")
            
            if msg.content.lower() == 'reset':
                await Guild.filter(guild_id=ctx.guild.id).update(welcome_banner=None)
                
                if ctx.guild.id in self.bot.cache.guild_data:
                    self.bot.cache.guild_data[ctx.guild.id]["welcome_banner"] = None
                
                return await ctx.success(f"{emote.check} Welcome banner reset to default!")
            
            banner_url = None
            if msg.attachments:
                banner_url = msg.attachments[0].url
            elif msg.content.startswith(('http://', 'https://')):
                banner_url = msg.content
            else:
                return await ctx.error("Invalid image URL or attachment!")
            
            async with self.bot.session.get(banner_url) as resp:
                if resp.status != 200:
                    return await ctx.error("Could not access the image!")
                
                content_type = resp.headers.get('content-type', '')
                if not content_type.startswith('image/'):
                    return await ctx.error("The URL must be an image or GIF!")
            
            await Guild.filter(guild_id=ctx.guild.id).update(welcome_banner=banner_url)
            
            if ctx.guild.id in self.bot.cache.guild_data:
                self.bot.cache.guild_data[ctx.guild.id]["welcome_banner"] = banner_url
            
            preview_embed = discord.Embed(
                color=discord.Color.green(),
                description=f"{emote.check} Custom welcome banner set successfully!\n\nPreview:"
            )
            preview_embed.set_image(url=banner_url)
            await ctx.send(embed=preview_embed)
            
        except asyncio.TimeoutError:
            await ctx.error("You took too long to respond!")

    @welcome.command(name="disable")
    @commands.has_permissions(administrator=True)
    async def welcome_disable(self, ctx: Context):
        """Disable welcome system for the server."""
        await Guild.filter(guild_id=ctx.guild.id).update(welcome_channel=None)
        
        if ctx.guild.id in self.bot.cache.guild_data:
            self.bot.cache.guild_data[ctx.guild.id]["welcome_channel"] = None
        
        await ctx.success(f"{emote.check} Welcome system has been disabled!")

    @welcome.command(name="status")
    @commands.has_permissions(administrator=True)
    async def welcome_status(self, ctx: Context):
        """Check welcome system status."""
        guild = await Guild.get_or_none(pk=ctx.guild.id)
        
        if not guild or not guild.welcome_channel:
            return await ctx.send(
                embed=discord.Embed(
                    color=discord.Color.red(),
                    description=f"{emote.xmark} Welcome system is **disabled** in this server.\n\nUse `{ctx.prefix}welcome setup #channel` to enable it."
                )
            )
        
        channel = ctx.guild.get_channel(guild.welcome_channel)
        
        if not channel:
            await Guild.filter(guild_id=ctx.guild.id).update(welcome_channel=None)
            return await ctx.error("Welcome channel was deleted. Please set a new one!")
        
        banner_status = "Custom Banner" if guild.welcome_banner else "Default Banners"
        
        embed = discord.Embed(
            color=discord.Color.green(),
            title=f"{emote.check} Welcome System Status",
            description=(
                f"**Status:** Enabled ✅\n"
                f"**Channel:** {channel.mention}\n"
                f"**Banner:** {banner_status}\n"
                f"**Total Members:** {ctx.guild.member_count}\n"
            )
        )
        
        if guild.welcome_banner:
            embed.set_thumbnail(url=guild.welcome_banner)
        
        await ctx.send(embed=embed)

    @welcome.command(name="test")
    @commands.has_permissions(administrator=True)
    async def welcome_test(self, ctx: Context, member: discord.Member = None):
        """Test welcome message. Usage: xwelcome test @member"""
        guild = await Guild.get_or_none(pk=ctx.guild.id)
        
        if not guild or not guild.welcome_channel:
            return await ctx.error(
                f"Welcome system is not setup! Use `{ctx.prefix}welcome setup #channel` first."
            )
        
        channel = ctx.guild.get_channel(guild.welcome_channel)
        
        if not channel:
            await Guild.filter(guild_id=ctx.guild.id).update(welcome_channel=None)
            return await ctx.error("Welcome channel was deleted. Please set a new one!")
        
        if member is None:
            member = ctx.author
        
        await self._send_welcome(member, channel, is_test=True)
        await ctx.success(f"Test welcome message sent to {channel.mention}!")

    async def _send_welcome(self, member: discord.Member, channel: discord.TextChannel, is_test: bool = False):
        """Internal method to send welcome message"""
        guild_data = await Guild.get_or_none(pk=member.guild.id)
        
        if guild_data and guild_data.welcome_banner:
            selected_gif = guild_data.welcome_banner
        else:
            welcome_gifs = [
                "https://cdn.discordapp.com/attachments/1430488136869216267/1431479480370597959/Discord_welcome_banner_with_Tenshi_Hinanawi.jpg?ex=68fd90a7&is=68fc3f27&hm=12a9604ca22aacb95c780f9df0b163d7013b50ea51acfdcbac2198a0a1c41ab7&",
            ]
            selected_gif = random.choice(welcome_gifs)
        
        embed = discord.Embed(
            color=discord.Color.from_rgb(88, 101, 242),
            timestamp=datetime.now()
        )
        
        embed.title = f"Welcome to {member.guild.name}!"
        
        embed.description = (
            f"Hey {member.mention}, welcome aboard!<a:Anime:1431632348239237201>\n\n"
            f"We're excited to have you here! Make yourself at home and don't forget to check out our channels.\n\n"
            f"<a:edit:1431499232296308738>**Member Info:**\n"
            f"<a:prettyarrowR:1431630280044712058> Username: **{member.name}**\n"
            f"<a:prettyarrowR:1431630280044712058> Tag: **{member.discriminator if member.discriminator != '0' else member.name}**\n"
            f"<a:prettyarrowR:1431630280044712058> ID: `{member.id}`\n"
            f"<a:prettyarrowR:1431630280044712058> Account Created: {discord.utils.format_dt(member.created_at, 'R')}\n"
        )
        
        member_count = len([m for m in member.guild.members if not m.bot])
        bot_count = len([m for m in member.guild.members if m.bot])
        
        embed.add_field(
            name="<a:edit:1431499232296308738> Server Stats",
            value=(
                f"<a:prettyarrowR:1431630280044712058> Total Members: **{member.guild.member_count}**\n"
                f"<a:prettyarrowR:1431630280044712058> Humans: **{member_count}**\n"
                f"<a:prettyarrowR:1431630280044712058> Bots: **{bot_count}**\n"
                f"<a:prettyarrowR:1431630280044712058> You are member **#{member.guild.member_count}**"
            ),
            inline=False
        )
        
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_image(url=selected_gif)
        embed.set_footer(
            text=f"{member.guild.name} • {'Test ' if is_test else ''}Welcome Message",
            icon_url=member.guild.icon.url if member.guild.icon else None
        )
        
        if member.guild.icon:
            embed.set_author(
                name=member.guild.name,
                icon_url=member.guild.icon.url
            )
        
        await channel.send(
            content=f"<a:redsparklies:1431489940029706384> Everyone welcome {member.mention}<a:redsparklies:1431489940029706384>{' (Test)' if is_test else ''}",
            embed=embed
        )

    @Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Automatically welcome new members"""
        guild = await Guild.get_or_none(pk=member.guild.id)
        
        if not guild or not guild.welcome_channel:
            return
        
        channel = member.guild.get_channel(guild.welcome_channel)
        
        if not channel or not channel.permissions_for(member.guild.me).send_messages:
            return
        
        await self._send_welcome(member, channel, is_test=False)

    @commands.command()
    @commands.bot_has_permissions(embed_links=True)
    async def pstatus(self, ctx: Context):
        """Get your ScrimX Premium status and the current server's."""
        user = await User.get_or_none(user_id=ctx.author.id)
        guild = await Guild.filter(guild_id=ctx.guild.id).first()

        if not user.is_premium:
            atext = "\n> Activated: No!"
        else:
            atext = f"\n> Activated: Yes!\n> Ending: {discord_timestamp(user.premium_expire_time,'f')}"

        if not guild.is_premium:
            btext = "\n> Activated: No!"
        else:
            booster = guild.booster or await self.bot.fetch_user(guild.made_premium_by)
            btext = f"\n> Activated: Yes!\n> Ending: {discord_timestamp(guild.premium_end_time,'f')}\n> Upgraded by: **{booster}**"

        embed = self.bot.embed(ctx, title="ScrimX Premium", url=f"{self.bot.config.WEBSITE}")
        embed.add_field(name="User", value=atext, inline=False)
        embed.add_field(name="Server", value=btext, inline=False)
        embed.set_thumbnail(url=ctx.guild.me.display_avatar.url)
        return await ctx.send(embed=embed)

    @commands.hybrid_command(aliases=("perks", "pro"))
    async def premium(self, ctx: Context):
        """Checkout ScrimX Premium Plans."""
        _e = discord.Embed(
            color=self.bot.config.COLOR,
            description=f"[**Features of ScrimX Pro -**]({self.bot.config.SERVER_LINK})\n\n"
            f"{emote.verify1} unlimited Waiting Setup.\n"
            f"{emote.verify1} Unlimited Scrims.\n"
            f"{emote.verify1} Unlimited Tournaments.\n"
            f"{emote.verify1} Custom Reactions for Regs.\n"
            f"{emote.verify1} Smart SSverification.\n"
            f"{emote.verify1} Cancel-Claim Panel.\n"
            f"{emote.verify1} Bot Customization (Avatar, Name, Banner).\n"
            f"{emote.verify1} Premium Role + more...\n",
        )

        v = discord.ui.View(timeout=None)
        v.add_item(PremiumPurchaseBtn())
        await ctx.send(embed=_e, view=v)

    @commands.group(invoke_without_command=True)
    @commands.is_owner()
    async def plans(self, ctx: Context):
        """Manage premium plans"""
        plans = await PremiumPlan.all().order_by("id")
        
        if not plans:
            return await ctx.send("❌ No plans found! Use `plans setup`")
        
        embed = discord.Embed(color=self.bot.color, title="📊 Premium Plans")
        for plan in plans:
            embed.add_field(
                name=f"{plan.name}",
                value=f"₹{plan.price} • {plan.duration.days}d",
                inline=False
            )
        await ctx.send(embed=embed)

    @plans.command(name="setup")
    @commands.is_owner()
    async def plans_setup(self, ctx: Context):
        """Insert premium plans"""
        await PremiumPlan.insert_plans()
        await ctx.success("Plans inserted!")

    @tasks.loop(hours=48)
    async def remind_peeps_to_pay(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(900)
        
        async for user in User.filter(is_premium=True, premium_expire_time__lte=datetime.now(tz=IST) + timedelta(days=4)):
            _u = await self.bot.getch(self.bot.get_user, self.bot.fetch_user, user.pk)
            if _u:
                if not await self.ensure_reminders(user.pk, user.premium_expire_time):
                    await self.bot.reminders.create_timer(user.premium_expire_time, "user_premium", user_id=user.pk)
                await remind_user_to_pay(_u, user)

        async for guild in Guild.filter(is_premium=True, premium_end_time__lte=datetime.now(IST) + timedelta(days=4)):
            _g = self.bot.get_guild(guild.pk)
            if not await self.ensure_reminders(guild.pk, guild.premium_end_time):
                await self.bot.reminders.create_timer(guild.premium_end_time, "guild_premium", guild_id=guild.pk)
            if _g:
                await remind_guild_to_pay(_g, guild)

    async def ensure_reminders(self, _id: int, _time: datetime) -> bool:
        return await Timer.filter(
            Q(event="guild_premium", extra={"args": [], "kwargs": {"guild_id": _id}})
            | Q(event="user_premium", extra={"args": [], "kwargs": {"user_id": _id}}),
            expires=_time,
        ).exists()

    def cog_unload(self):
        self.remind_peeps_to_pay.stop()
        self.setup_premium_plans.stop()

    @Cog.listener()
    async def on_guild_premium_timer_complete(self, timer: Timer):
        guild_id = timer.kwargs["guild_id"]
        _g = await Guild.get_or_none(pk=guild_id)
        if not _g or not _g.premium_end_time == timer.expires:
            return

        _perks = "\n".join(await extra_guild_perks(guild_id))
        await deactivate_premium(guild_id)

        if (_ch := _g.private_ch) and _ch.permissions_for(_ch.guild.me).embed_links:
            _e = discord.Embed(
                color=discord.Color.red(), 
                title="⚠️__**ScrimX Pro Subscription Ended**__⚠️", 
                url=config.SERVER_LINK
            )
            _e.description = (
                "This is to inform you that your subscription of ScrimX Pro has been ended.\n\n"
                "*Following is a list of perks or data you lost:*"
            )
            _e.description += f"```diff\n{_perks}```"

            _roles = [
                role.mention
                for role in _ch.guild.roles
                if all((role.permissions.administrator, not role.managed, role.members))
            ]

            _view = PremiumView()
            await _ch.send(
                embed=_e,
                view=_view,
                content=", ".join(_roles[:2]) if _roles else _ch.guild.owner.mention,
                allowed_mentions=discord.AllowedMentions(roles=True),
            )

    @Cog.listener()
    async def on_user_premium_timer_complete(self, timer: Timer):
        user_id = timer.kwargs["user_id"]
        _user = await User.get(pk=user_id)

        if not _user.premium_expire_time == timer.expires:
            return

        _q = "UPDATE user_data SET is_premium = FALSE ,premiums=0 ,made_premium = '{}' WHERE user_id = $1"
        await self.bot.db.execute(_q, user_id)

        member = await self.bot.get_or_fetch_member(self.bot.server, _user.pk)
        if member:
            await member.remove_roles(discord.Object(id=config.PREMIUM_ROLE))

    @Cog.listener()
    async def on_premium_purchase(self, txnId: str):
        record = await PremiumTxn.get(txnid=txnId)
        member = self.bot.server.get_member(record.user_id)
        
        if member is not None:
            await member.add_roles(discord.Object(id=self.bot.config.PREMIUM_ROLE), reason="They purchased premium.")
        else:
            member = await self.bot.getch(self.bot.get_user, self.bot.fetch_user, record.user_id)

        with suppress(discord.HTTPException, AttributeError):
            _e = discord.Embed(
                color=discord.Color.gold(), 
                description=f"Thanks **{member}** for purchasing ScrimX Premium."
            )
            _e.set_image(url=random_thanks())
            await self.hook.send(embed=_e, username="premium-logs", avatar_url=self.bot.config.PREMIUM_AVATAR)

        upgraded_guild = self.bot.get_guild(record.guild_id)
        _guild = await Guild.get_or_none(pk=record.guild_id)

        _e = discord.Embed(
            color=self.bot.color,
            title="Scrimx Pro Purchase Successful!",
            url=self.bot.config.SERVER_LINK,
            description=(
                f"{random_greeting()} {member.mention},\n"
                f"Thanks for purchasing ScrimX Premium. Your server **{upgraded_guild}** has access to ScrimX Pro features until `{_guild.premium_end_time.strftime('%d-%b-%Y %I:%M %p')}`.\n\n"
                "[Click me to Invite ScrimX Pro Bot to your server](https://discord.com/oauth2/authorize?client_id=902856923311919104&scope=applications.commands%20bot&permissions=21175985838)\n"
            ),
        )

        if member not in self.bot.server.members:
            _e.description += f"\n\n[To claim your Premium Role, Join ScrimX HQ]({self.bot.config.SERVER_LINK})."

        _view = discord.ui.View(timeout=None)

        try:
            await member.send(embed=_e, view=_view)
        except discord.HTTPException:
            pass


async def setup(bot: Quotient) -> None:
    await bot.add_cog(PremiumCog(bot))
