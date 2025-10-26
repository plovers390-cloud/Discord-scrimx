from typing import List

import discord

import config
from models import PremiumPlan, PremiumTxn
from utils import emote


class PremiumPurchaseBtn(discord.ui.Button):
    def __init__(self, label="Get ScrimX Pro", emoji=emote.diamond, style=discord.ButtonStyle.grey):
        super().__init__(style=style, label=label, emoji=emoji)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        # Hardcoded owner ID
        OWNER_ID = 584926650492387351
        
        # Get bot owner
        bot_owner = await interaction.client.fetch_user(OWNER_ID)
        
        # Create simple embed
        embed = discord.Embed(
            color=discord.Color.gold(),
            title=f"{emote.crown} ScrimX Premium",
            description=(
                f"<a:Anime:1431632348239237201> **Contact Bot Owner to add premium to this server**\n\n"
                f"<a:prettyarrowR:1431681727629361222>**Server:** {interaction.guild.name}\n"
                f"<a:prettyarrowR:1431681727629361222>**Your ID:** `{interaction.user.id}`\n"
            )
        )
        
        # Bot avatar on right side
        embed.set_thumbnail(url=interaction.client.user.display_avatar.url)
        
        # Add server link field
        embed.add_field(
            name="<a:edit:1431499232296308738> Support Server",
            value=f"[Join ScrimX HQ]({config.SERVER_LINK})",
            inline=False
        )
        
        # Add owner info
        embed.add_field(
            name="<a:ice:1431645234437161060> Bot Owner",
            value=f"{bot_owner.mention} • `{bot_owner.id}`",
            inline=False
        )
        
        embed.set_footer(text="Contact owner for premium activation")
        
        # Create view with server link button
        view = discord.ui.View()
        view.add_item(discord.ui.Button(
            label="Join Support Server",
            url=config.SERVER_LINK,
            style=discord.ButtonStyle.link,
            emoji="🔗"
        ))
        
        await interaction.followup.send(
            embed=embed,
            view=view,
            ephemeral=True
        )


class PremiumView(discord.ui.View):
    def __init__(self, text="This feature requires ScrimX Premium.", *, label="Get ScrimX Pro"):
        super().__init__(timeout=None)
        self.text = text
        self.add_item(PremiumPurchaseBtn(label=label))

    @property
    def premium_embed(self) -> discord.Embed:
        _e = discord.Embed(
            color=0xFF0000, 
            description=f"**You discovered a premium feature <a:orb:891604865627873280>**"
        )
        _e.description = (
            f"\n*`{self.text}`*\n\n"
            "__Perks you get with ScrimX Pro:__\n"
            f"{emote.verify1} Unlimited Waiting Setup.\n"
            f"{emote.verify1} Unlimited Scrims.\n"
            f"{emote.verify1} Unlimited Tournaments.\n"
            f"{emote.verify1} Custom Reactions for Regs.\n"
            f"{emote.verify1} Smart SSverification.\n"
            f"{emote.verify1} Cancel-Claim Panel.\n"
            f"{emote.verify1} Bot Customization (Avatar, Name, Banner).\n"
            f"{emote.verify1} Premium Role + more...\n"
        )
        return _e