from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, List
from datetime import datetime, timedelta
from collections import defaultdict, deque
from contextlib import suppress
import base64

import discord
import humanize
import google.generativeai as genai

from constants import SSType

if TYPE_CHECKING:
    from core import Quotient

from core import Cog, Context, QuotientRatelimiter
from models import ImageResponse, SSVerify
from utils import emote, plural


class MemberLimits(defaultdict):
    def __missing__(self, key):
        r = self[key] = QuotientRatelimiter(1, 7)
        return r


class GuildLimits(defaultdict):
    def __missing__(self, key):
        r = self[key] = QuotientRatelimiter(10, 60)
        return r


class Ssverification(Cog):
    def __init__(self, bot: Quotient):
        self.bot = bot

        # Initialize Gemini AI
        genai.configure(api_key=bot.config.GEMINI_API_KEY)
        self.gemini_model = genai.GenerativeModel('gemini-2.0-flash-001')  # Latest Gemini 2.0 model
        print("✅ Gemini 2.0 Flash initialized for SS Verification")

        # Gemini Rate Limiting
        self.gemini_rpm_queue = deque()  # Requests per minute
        self.gemini_daily_counter = 0
        self.gemini_last_reset = datetime.utcnow().date()
        self.max_gemini_rpm = 14  # Safety margin (actual: 15)
        self.max_gemini_rpd = 1400  # Safety margin (actual: 1500)

        # User/Guild rate limiters
        self.__mratelimiter = MemberLimits(QuotientRatelimiter)
        self.__gratelimiter = GuildLimits(QuotientRatelimiter)
        self.__verify_lock = asyncio.Lock()

    async def check_gemini_rate_limit(self) -> tuple[bool, str]:
        """Check Gemini API rate limits"""
        # Reset daily counter at midnight UTC
        today = datetime.utcnow().date()
        if today > self.gemini_last_reset:
            self.gemini_daily_counter = 0
            self.gemini_last_reset = today
            print(f"✅ Gemini daily quota reset! Date: {today}")

        # Check daily limit
        if self.gemini_daily_counter >= self.max_gemini_rpd:
            hours_until_reset = 24 - datetime.utcnow().hour
            return False, f"⏰ Daily AI limit reached. Resets in ~{hours_until_reset} hours."

        # Check per-minute limit
        now = datetime.utcnow()
        
        # Remove requests older than 1 minute
        while self.gemini_rpm_queue and self.gemini_rpm_queue[0] < now - timedelta(minutes=1):
            self.gemini_rpm_queue.popleft()

        if len(self.gemini_rpm_queue) >= self.max_gemini_rpm:
            wait_time = 60 - (now - self.gemini_rpm_queue[0]).seconds
            return False, f"⏳ AI rate limit reached. Wait {wait_time}s."

        return True, "OK"

    async def verify_with_gemini(self, image_url: str, record: SSVerify) -> ImageResponse:
        """Verify screenshot using Gemini AI"""
        try:
            # Check rate limit
            can_proceed, message = await self.check_gemini_rate_limit()
            if not can_proceed:
                return ImageResponse(
                    url=image_url,
                    text=message,
                    dhash="0" * 16,
                    phash="0" * 16
                )

            # Download image
            async with self.bot.session.get(image_url) as resp:
                if resp.status != 200:
                    return ImageResponse(
                        url=image_url,
                        text="Failed to download image",
                        dhash="0" * 16,
                        phash="0" * 16
                    )
                image_data = await resp.read()

            # Convert to base64
            image_b64 = base64.b64encode(image_data).decode()

            # Create verification prompt based on SS type
            prompt = await self._create_verification_prompt(record)

            # Call Gemini API with proper format for vision model
            response = self.gemini_model.generate_content([
                {
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": "image/png",
                                "data": image_b64
                            }
                        }
                    ]
                }
            ])

            # Update rate limit counters
            self.gemini_rpm_queue.append(datetime.utcnow())
            self.gemini_daily_counter += 1

            # Log usage
            print(f"📊 Gemini: {self.gemini_daily_counter}/{self.max_gemini_rpd} daily | {len(self.gemini_rpm_queue)}/{self.max_gemini_rpm} rpm")

            # Parse response
            text = response.text.strip()
            
            # Check if verification passed
            is_valid = self._parse_gemini_response(text, record)

            # Generate proper hexadecimal hashes (64 characters for imagehash compatibility)
            import hashlib
            url_hash = hashlib.md5(image_url.encode()).hexdigest()[:16]  # 16 hex chars
            text_hash = hashlib.md5(text.encode()).hexdigest()[:16]  # 16 hex chars

            return ImageResponse(
                url=image_url,
                text=text,
                dhash=url_hash,  # Valid hex hash
                phash=text_hash  # Valid hex hash (removed is_valid since it doesn't exist in model)
            )

        except Exception as e:
            error_msg = str(e)
            print(f"❌ Gemini Error: {error_msg}")
            
            if "429" in error_msg or "quota" in error_msg.lower():
                return ImageResponse(
                    url=image_url,
                    text="⏰ AI quota exceeded. Please try again later.",
                    dhash="0" * 16,
                    phash="0" * 16
                )
            
            return ImageResponse(
                url=image_url,
                text=f"AI Error: {error_msg[:100]}",
                dhash="0" * 16,
                phash="0" * 16
            )

    async def _create_verification_prompt(self, record: SSVerify) -> str:
        """Create appropriate prompt based on SS type"""
        base_prompt = "Analyze this screenshot carefully.\n\n"

        if record.ss_type == SSType.anyss:
            return base_prompt + "Is this a valid screenshot? Reply with: VALID: YES or NO"

        elif record.ss_type == SSType.yt:
            return base_prompt + """Check if this is a YouTube screenshot.
Look for:
- YouTube interface elements
- Video player controls
- YouTube branding
- Channel name/subscribe button

Reply in format:
VALID: YES or NO
REASON: (brief explanation)"""

        elif record.ss_type == SSType.insta:
            return base_prompt + """Check if this is an Instagram screenshot.
Look for:
- Instagram interface (heart icon, comment icon, share icon)
- Instagram post format
- Instagram Stories format
- Profile pictures and usernames

Reply in format:
VALID: YES or NO
REASON: (brief explanation)"""

        elif record.ss_type == SSType.loco:
            return base_prompt + """Check if this is a Loco app screenshot.
Look for:
- Loco app interface
- Gaming streams
- Loco branding/logo
- Diamond counts or rewards

Reply in format:
VALID: YES or NO
REASON: (brief explanation)"""

        elif record.ss_type == SSType.rooter:
            return base_prompt + """Check if this is a Rooter app screenshot.
Look for:
- Rooter app interface
- Sports streaming
- Rooter branding
- Predictions or fantasy elements

Reply in format:
VALID: YES or NO
REASON: (brief explanation)"""

        elif record.ss_type == SSType.custom:
            custom_text = getattr(record, 'custom_text', '')
            return base_prompt + f"""Check if this screenshot contains the text: "{custom_text}"

Look carefully at all visible text in the image.

Reply in format:
VALID: YES or NO
TEXT_FOUND: (what text you see)
CONFIDENCE: (0-100%)"""

        return base_prompt + "Is this a valid screenshot? Reply YES or NO"

    def _parse_gemini_response(self, text: str, record: SSVerify) -> bool:
        """Parse Gemini response to determine if verification passed"""
        text_upper = text.upper()
        
        # Look for validation keywords
        if "VALID: YES" in text_upper or "YES" in text_upper[:30]:
            return True
        
        if "VALID: NO" in text_upper or "NOT VALID" in text_upper:
            return False
        
        # For custom type, check confidence
        if record.ss_type == SSType.custom:
            if "CONFIDENCE:" in text_upper:
                try:
                    # Extract confidence percentage
                    conf_part = text.split("CONFIDENCE:")[1].split("%")[0].strip()
                    confidence = int(''.join(filter(str.isdigit, conf_part)))
                    return confidence >= 70  # 70% threshold
                except:
                    pass
        
        # Default: check if "YES" appears before "NO"
        yes_pos = text_upper.find("YES")
        no_pos = text_upper.find("NO")
        
        if yes_pos != -1 and (no_pos == -1 or yes_pos < no_pos):
            return True
        
        return False

    async def __check_ratelimit(self, message: discord.Message):
        if retry := self.__mratelimiter[message.author].is_ratelimited(message.author):
            await message.reply(
                embed=discord.Embed(
                    color=discord.Color.red(),
                    description=f"**You are too fast. Kindly resend after `{retry:.2f}` seconds.**",
                )
            )
            return False

        elif retry := self.__gratelimiter[message.guild].is_ratelimited(message.guild):
            await message.reply(
                embed=discord.Embed(
                    color=discord.Color.red(),
                    description=f"**Many users are submitting screenshots from this server at this time. Kindly retry after `{retry:.2f}` seconds.**",
                )
            )
            return False
        return True

    @Cog.listener()
    async def on_message(self, message: discord.Message):
        if not all(
            (
                message.guild,
                not message.author.bot,
                message.channel.id in self.bot.cache.ssverify_channels,
            )
        ):
            return

        record = await SSVerify.get_or_none(channel_id=message.channel.id)
        if not record:
            return self.bot.cache.ssverify_channels.discard(message.channel.id)

        if "tourney-mod" in (role.name.lower() for role in message.author.roles):
            return

        ctx: Context = await self.bot.get_context(message)

        _e = discord.Embed(color=discord.Color.red())

        with suppress(discord.HTTPException):
            if await record.is_user_verified(message.author.id):
                _e.description = "**Your screenshots are already verified, kindly move onto next step.**"
                return await ctx.reply(embed=_e)

            if not (attachments := self.__valid_attachments(message)):
                _e.description = "**Kindly send screenshots in `png/jpg/jpeg` format only.**"
                return await ctx.reply(embed=_e)

            if not await self.__check_ratelimit(message):
                return

            if len(attachments) > record.required_ss:
                _e.description = (
                    f"**You only have to send `{record.required_ss}` screenshots but you sent `{len(attachments)}`**"
                )
                return await ctx.reply(embed=_e)

            _e.color = discord.Color.yellow()
            _e.description = f"Processing your {plural(attachments):screenshot|screenshots}... ⏳"
            m: discord.Message = await message.reply(embed=_e)

            start_at = self.bot.current_time

            # Process with Gemini AI
            async with self.__verify_lock:
                _ocr = []
                for attachment in attachments:
                    result = await self.verify_with_gemini(attachment.proxy_url, record)
                    _ocr.append(result)

            complete_at = self.bot.current_time

            embed = await self.__verify_screenshots(ctx, record, _ocr)
            embed.set_footer(text=f"Time taken: {humanize.precisedelta(complete_at-start_at)} | Powered by Gemini AI")
            embed.set_author(
                name=f"Submitted {await record.data.filter(author_id=ctx.author.id).count()}/{record.required_ss}",
                icon_url=getattr(ctx.author.display_avatar, "url", None),
            )

            with suppress(discord.HTTPException):
                await m.delete()

            await message.reply(embed=embed)

            if await record.is_user_verified(ctx.author.id):
                await message.author.add_roles(discord.Object(id=record.role_id))

                if record.success_message:
                    _e.title = f"Screenshot Verification Complete"
                    _e.url, _e.description = message.jump_url, record.success_message
                    return await message.reply(embed=_e)

                _e.description = f"{ctx.author.mention} Your screenshots are verified, Move to next step."
                await message.reply(embed=_e)

    async def __verify_screenshots(self, ctx: Context, record: SSVerify, _ocr: List[ImageResponse]) -> discord.Embed:
        _e = discord.Embed(color=self.bot.color, description="")

        for _ in _ocr:
            if not record.allow_same:
                b, t = await record._match_for_duplicate(_.dhash, _.phash, ctx.author.id)
                if b:
                    _e.description += t
                    continue

            # Parse validation from text (since ImageResponse doesn't have is_valid field)
            is_valid = self._parse_gemini_response(_.text, record)

            if record.ss_type == SSType.anyss:
                if is_valid:
                    _e.description += f"{record.emoji(True)} | Successfully Verified.\n"
                    await record._add_to_data(ctx, _)
                else:
                    _e.description += f"{record.emoji(False)} | Verification Failed: {_.text[:100]}\n"

            elif record.ss_type == SSType.yt:
                _e.description += await record.verify_yt(ctx, _)

            elif record.ss_type == SSType.insta:
                _e.description += await record.verify_insta(ctx, _)

            elif record.ss_type == SSType.loco:
                _e.description += await record.verify_loco(ctx, _)

            elif record.ss_type == SSType.rooter:
                _e.description += await record.verify_rooter(ctx, _)

            elif record.ss_type == SSType.custom:
                _e.description += await record.verify_custom(ctx, _)

        return _e

    def __valid_attachments(self, message: discord.Message):
        return [_ for _ in message.attachments if _.content_type in ("image/png", "image/jpeg", "image/jpg")]

    @Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.TextChannel):
        if channel.id in self.bot.cache.ssverify_channels:
            record = await SSVerify.get_or_none(channel_id=channel.id)
            if record:
                await record.full_delete()

    @Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        records = await SSVerify.filter(role_id=role.id)
        if records:
            for record in records:
                await record.full_delete()