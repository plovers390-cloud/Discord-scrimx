from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING, List
from datetime import datetime, timedelta
from collections import defaultdict, deque
from contextlib import suppress
import hashlib
import re

import discord
import humanize
import pytesseract
from PIL import Image
import io
import imagehash

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

        # Initialize Tesseract OCR
        try:
            tesseract_path = [
                '/usr/bin/tesseract',
                'usr/local/bin/tesseract',
                'tesseract'
            ]

            tesseract_found =False
            for path in tesseract_path:
                if path == 'tesseract' or os.path.exists(path):
                    pytesseract.pytesseract.tesseract_cmd = path
                    try:
                        pytesseract.get_tesseract_version()
                        tesseract_found =True
                        break
                    except:
                        continue
            if not tesseract_found:
                raise Esception('Tesseract not found in system')
            
        except Exception as e:
            pass

        # Stats
        self.stats = {
            'total_verified': 0,
            'today_verified': 0,
            'last_reset': datetime.utcnow().date()
        }

        # Rate limiters
        self.__mratelimiter = MemberLimits(QuotientRatelimiter)
        self.__gratelimiter = GuildLimits(QuotientRatelimiter)
        self.__verify_lock = asyncio.Lock()

    async def calculate_image_hashes(self, image_data: bytes) -> tuple[str, str]:
        """Calculate hashes for duplicate detection"""
        try:
            def _calc():
                image = Image.open(io.BytesIO(image_data))
                dhash = str(imagehash.dhash(image))
                phash = str(imagehash.phash(image))
                ahash = str(imagehash.average_hash(image))
                whash = str(imagehash.whash(image))
                combined = f"{dhash}:{phash}:{ahash}:{whash}"
                return dhash, combined
            
            dhash, combined = await asyncio.to_thread(_calc)
            return dhash, combined
        except Exception as e:
            print(f"❌ Hash error: {e}")
            fallback = hashlib.md5(image_data).hexdigest()[:16]
            return fallback, fallback

    def calculate_hash_similarity(self, hash1: str, hash2: str) -> float:
        """Calculate similarity between hashes"""
        try:
            h1_parts = hash1.split(':')
            h2_parts = hash2.split(':')
            
            if len(h1_parts) != len(h2_parts):
                return 0.0
            
            similarities = []
            for h1, h2 in zip(h1_parts, h2_parts):
                if len(h1) != len(h2):
                    continue
                differences = sum(c1 != c2 for c1, c2 in zip(h1, h2))
                similarity = (1 - (differences / len(h1))) * 100
                similarities.append(similarity)
            
            return sum(similarities) / len(similarities) if similarities else 0.0
        except:
            return 0.0

    async def extract_text_with_tesseract(self, image_data: bytes) -> tuple[str, dict]:
        """Extract text + device info"""
        try:
            def _extract():
                image = Image.open(io.BytesIO(image_data))
                width, height = image.size
                aspect_ratio = width / height
                
                device_info = {
                    'width': width,
                    'height': height,
                    'aspect_ratio': round(aspect_ratio, 2),
                    'device_type': 'unknown',
                    'platform': 'unknown'
                }
                
                if aspect_ratio > 1.5:
                    device_info['device_type'] = 'desktop'
                    device_info['platform'] = 'web'
                elif 0.4 < aspect_ratio < 0.6:
                    device_info['device_type'] = 'mobile'
                    device_info['platform'] = 'app'
                elif 0.8 < aspect_ratio < 1.2:
                    device_info['device_type'] = 'tablet'
                    device_info['platform'] = 'app'
                
                mobile_res = [(1080, 1920), (1080, 2340), (1080, 2400), (1440, 3040), (720, 1280)]
                for mw, mh in mobile_res:
                    if (width == mw and height == mh) or (width == mh and height == mw):
                        device_info['device_type'] = 'mobile'
                        device_info['platform'] = 'app'
                        break
                
                image = image.convert('L')
                text = pytesseract.image_to_string(image, lang='eng', config='--psm 6 --oem 3')
                return text.strip(), device_info
            
            text, device_info = await asyncio.to_thread(_extract)
            if text:
                print(f"📝 OCR: {len(text)} chars | {device_info['device_type']} ({device_info['width']}x{device_info['height']})")
            return text, device_info
        except Exception as e:
            print(f"❌ OCR Error: {e}")
            return "", {'device_type': 'unknown', 'platform': 'unknown', 'width': 0, 'height': 0}

    def extract_counts_from_text(self, text: str, ss_type: SSType) -> dict:
        """Extract follower/subscriber counts"""
        counts = {
            'followers': None, 'following': None, 'subscribers': None,
            'views': None, 'likes': None, 'posts': None
        }
        
        text_lower = text.lower()
        
        if ss_type == SSType.yt:
            # Subscribers
            patterns = [
                r'(\d+(?:\.\d+)?)\s*[KkMmBb]?\s*subscriber',
                r'subscriber[s]?\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*[KkMmBb]?',
            ]
            for pattern in patterns:
                if match := re.search(pattern, text_lower):
                    counts['subscribers'] = self._parse_count(match.group(1))
                    break
            
            # Views
            patterns = [
                r'(\d+(?:\.\d+)?)\s*[KkMmBb]?\s*views?',
                r'views?\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*[KkMmBb]?',
            ]
            for pattern in patterns:
                if match := re.search(pattern, text_lower):
                    counts['views'] = self._parse_count(match.group(1))
                    break
        
        elif ss_type == SSType.insta:
            # Followers
            patterns = [
                r'(\d+(?:\.\d+)?)\s*[KkMmBb]?\s*followers?',
                r'followers?\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*[KkMmBb]?',
            ]
            for pattern in patterns:
                if match := re.search(pattern, text_lower):
                    counts['followers'] = self._parse_count(match.group(1))
                    break
            
            # Following
            patterns = [
                r'(\d+(?:\.\d+)?)\s*[KkMmBb]?\s*following',
                r'following\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*[KkMmBb]?',
            ]
            for pattern in patterns:
                if match := re.search(pattern, text_lower):
                    counts['following'] = self._parse_count(match.group(1))
                    break
            
            # Posts
            patterns = [
                r'(\d+(?:\.\d+)?)\s*[KkMmBb]?\s*posts?',
                r'posts?\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*[KkMmBb]?',
            ]
            for pattern in patterns:
                if match := re.search(pattern, text_lower):
                    counts['posts'] = self._parse_count(match.group(1))
                    break
        
        return counts

    def _parse_count(self, count_str: str) -> int:
        """Convert count string to integer"""
        try:
            count_str = count_str.replace(',', '').strip()
            multipliers = {'k': 1000, 'm': 1000000, 'b': 1000000000}
            
            for suffix, mult in multipliers.items():
                if count_str.lower().endswith(suffix):
                    return int(float(count_str[:-1]) * mult)
            
            return int(float(count_str))
        except:
            return 0

    async def check_count_increment(self, record: SSVerify, ctx: Context, new_counts: dict) -> tuple[bool, str]:
        """Check if counts increased"""
        try:
            previous = await record.data.filter(author_id=ctx.author.id).order_by('id').all()
            
            if not previous:
                if record.ss_type == SSType.yt and new_counts.get('subscribers'):
                    return True, f"✅ Subscribers: {new_counts['subscribers']:,}"
                elif record.ss_type == SSType.insta and new_counts.get('followers'):
                    return True, f"✅ Followers: {new_counts['followers']:,}"
                return True, "✅ First submission"
            
            # Get most recent with counts
            prev_counts = None
            for prev in reversed(previous):
                if hasattr(prev, 'metadata') and prev.metadata:
                    prev_counts = prev.metadata.get('counts', {})
                    if prev_counts and (prev_counts.get('subscribers') or prev_counts.get('followers')):
                        break
            
            if not prev_counts:
                return True, "✅ No previous data"
            
            # Compare
            if record.ss_type == SSType.yt:
                old = prev_counts.get('subscribers', 0)
                new = new_counts.get('subscribers', 0)
                
                if not new:
                    return False, "❌ Subscriber count not detected in screenshot"
                
                if new > old:
                    return True, f"✅ Subs: {old:,} → {new:,} (+{new-old:,})"
                elif new == old:
                    return False, f"❌ Subs unchanged: {old:,}"
                else:
                    return False, f"❌ Subs decreased: {old:,} → {new:,}"
            
            elif record.ss_type == SSType.insta:
                old = prev_counts.get('followers', 0)
                new = new_counts.get('followers', 0)
                
                if not new:
                    return False, "❌ Follower count not detected in screenshot"
                
                if new > old:
                    return True, f"✅ Followers: {old:,} → {new:,} (+{new-old:,})"
                elif new == old:
                    return False, f"❌ Followers unchanged: {old:,}"
                else:
                    return False, f"❌ Followers decreased: {old:,} → {new:,}"
            
            return True, "✅ Count check not required"
        except Exception as e:
            print(f"❌ Count check error: {e}")
            return True, "✅ Count check skipped"

    async def verify_screenshot_ocr(self, image_url: str, record: SSVerify, ctx: Context) -> ImageResponse:
        """OCR-only verification with ordered checks"""
        try:
            
            # Download image
            async with self.bot.session.get(image_url) as resp:
                if resp.status != 200:
                    return ImageResponse(
                        url=image_url, 
                        text="❌ Failed to download image", 
                        dhash="0"*16, 
                        phash="0"*16, 
                        metadata={'error': 'download_failed'}
                    )
                image_data = await resp.read()
            
            # Step 1: Calculate hashes
            hash_task = asyncio.create_task(self.calculate_image_hashes(image_data))
            
            # Step 2: Run OCR
            text_task = asyncio.create_task(self.extract_text_with_tesseract(image_data))
            
            dhash, phash = await hash_task
            ocr_text, device_info = await text_task
            
            # Validation order
            result_text = ""
            is_valid = False
            validation_steps = []
            
            # Step 1: OCR Text Detection
            if not ocr_text or len(ocr_text.strip()) < 10:
                validation_steps.append("❌ No text detected in image")
                result_text = self._build_result_text(False, validation_steps, device_info, {}, ocr_text)
                return ImageResponse(
                    url=image_url,
                    text=result_text,
                    dhash=dhash,
                    phash=phash,
                    metadata={'device_info': device_info, 'counts': {}, 'timestamp': datetime.utcnow().isoformat()}
                )
            
            validation_steps.append(f"✅ Step 1: Text detected ({len(ocr_text)} characters)")
            
            # Step 3: Channel Name Check (for YT/Insta)
            if record.ss_type in [SSType.yt, SSType.insta]:
                channel_name = getattr(record, 'channel_name', None) or getattr(record, 'channel_url', '')
                if channel_name:
                    channel_valid = channel_name.lower() in ocr_text.lower()
                    if not channel_valid:
                        validation_steps.append(f"❌ Wrong SS! Verified Channel name is '{channel_name}' ")
                        result_text = self._build_result_text(False, validation_steps, device_info, {}, ocr_text)
                        return ImageResponse(
                            url=image_url,
                            text=result_text,
                            dhash=dhash,
                            phash=phash,
                            metadata={'device_info': device_info, 'counts': {}, 'timestamp': datetime.utcnow().isoformat()}
                        )
                    validation_steps.append(f"✅ Step 3: Channel name verified")
                else:
                    validation_steps.append("⚠️ Step 3: No channel name to verify")
            
            # Step 4: Subscribe/Follow Button Check
            action_valid, action_msg = self._check_action_button(ocr_text, record)
            if not action_valid:
                validation_steps.append(f"❌ Step 4: {action_msg}")
                result_text = self._build_result_text(False, validation_steps, device_info, {}, ocr_text)
                return ImageResponse(
                    url=image_url,
                    text=result_text,
                    dhash=dhash,
                    phash=phash,
                    metadata={'device_info': device_info, 'counts': {}, 'timestamp': datetime.utcnow().isoformat()}
                )
            
            validation_steps.append(f"✅ Step 4: {action_msg}")
            
            # REMOVED: Step 5 - Follower/Subscriber Count Check
            # Count extraction still done for metadata but not validated
            counts = self.extract_counts_from_text(ocr_text, record.ss_type)
            
            # All checks passed
            is_valid = True
            result_text = self._build_result_text(True, validation_steps, device_info, counts, ocr_text)
            
            return ImageResponse(
                url=image_url,
                text=result_text,
                dhash=dhash,
                phash=phash,
                metadata={'device_info': device_info, 'counts': counts, 'timestamp': datetime.utcnow().isoformat()}
            )
            
        except Exception as e:
            print(f"❌ OCR Verification error: {e}")
            return ImageResponse(
                url=image_url, 
                text=f"❌ Error: {e}", 
                dhash="0"*16, 
                phash="0"*16, 
                metadata={'error': str(e)}
            )

    def _validate_platform(self, text: str, record: SSVerify) -> tuple[bool, str]:
        """Validate screenshot is from correct platform"""
        text_lower = text.lower()
        
        if record.ss_type == SSType.yt:
            keywords = ['youtube', 'subscribe', 'subscribed', 'views', 'view']
            found = [k for k in keywords if k in text_lower]
            if len(found) >= 2:
                return True, f"YouTube platform verified"
            return False, f"Not a YouTube screenshot"
        
        elif record.ss_type == SSType.insta:
            keywords = ['instagram', 'followers', 'following', 'follow', 'posts']
            found = [k for k in keywords if k in text_lower]
            if len(found) >= 2:
                return True, f"Instagram platform verified"
            return False, f"Not an Instagram screenshot"
        
        elif record.ss_type == SSType.loco:
            keywords = ['loco', 'diamonds', 'stream', 'live']
            found = [k for k in keywords if k in text_lower]
            if len(found) >= 1:
                return True, f"Loco platform verified"
            return False, f"Not a Loco screenshot"
        
        elif record.ss_type == SSType.rooter:
            keywords = ['rooter', 'predict', 'fantasy']
            found = [k for k in keywords if k in text_lower]
            if len(found) >= 1:
                return True, f"Rooter platform verified"
            return False, f"Not a Rooter screenshot"
        
        elif record.ss_type == SSType.custom:
            custom_text = getattr(record, 'custom_text', '')
            if custom_text and custom_text.lower() in text_lower:
                return True, f"Custom text found"
            return False, f"Custom text not found"
        
        return True, "Platform check passed"

    def _check_action_button(self, text: str, record: SSVerify) -> tuple[bool, str]:
     """Check for subscribe/follow button"""
     text_lower = text.lower()
    
     if record.ss_type == SSType.yt:
        # Check for "Subscribe" or "Subscribed"
        has_subscribe = 'subscribe' in text_lower
        has_subscribed = 'subscribed' in text_lower
        
        if has_subscribed:
            return True, "Subscribed ✓ (Already subscribed)"
        elif has_subscribe and not has_subscribed:
            return False, "Subscribe button found - Please subscribe first!"
        else:
            return False, "Subscribe/Subscribed button not found in screenshot"
    
     elif record.ss_type == SSType.insta:
        has_follow = 'follow' in text_lower
        has_following = 'following' in text_lower
        
        if has_following:
            return True, "Following ✓ (Already following)"
        elif has_follow and not has_following:
            return False, "Follow button found - Please follow first!"
        else:
            return False, "Follow/Following button not found in screenshot"
    
     return True, "Action check passed"

    def _build_result_text(self, is_valid: bool, steps: List[str], device_info: dict, counts: dict, ocr_text: str) -> str:
        """Build formatted result text"""
        result = f"VALID: {'YES' if is_valid else 'NO'}\n\n"
        result += "[Verification Steps]\n"
        for step in steps:
            result += f"{step}\n"
        result += "\n"
        
        result += f"[Device] {device_info.get('device_type', 'unknown')} | "
        result += f"{device_info.get('width', 0)}x{device_info.get('height', 0)}\n\n"
        
        if counts.get('subscribers') or counts.get('followers'):
            result += "[Counts]\n"
            if counts.get('subscribers'):
                result += f"Subscribers: {counts['subscribers']:,}\n"
            if counts.get('followers'):
                result += f"Followers: {counts['followers']:,}\n"
            if counts.get('following'):
                result += f"Following: {counts['following']:,}\n"
            if counts.get('posts'):
                result += f"Posts: {counts['posts']:,}\n"
            result += "\n"
        
        result += f"[OCR Text]\n{ocr_text[:300]}"
        return result

    async def __ensure_channel_permissions(self, channel: discord.TextChannel):
        """Ensure proper channel permissions"""
        try:
            everyone_role = channel.guild.default_role
            bot_member = channel.guild.me
            
            everyone_overwrites = discord.PermissionOverwrite(
                view_channel=True, read_messages=True, send_messages=True,
                attach_files=True, add_reactions=True,
                read_message_history=False, embed_links=False, mention_everyone=False,
                use_external_emojis=False, use_external_stickers=False,
                manage_messages=False, manage_channels=False, manage_webhooks=False,
                create_public_threads=False, create_private_threads=False,
                send_messages_in_threads=False, use_application_commands=False,
            )
            
            bot_overwrites = discord.PermissionOverwrite(
                view_channel=True, read_messages=True, send_messages=True,
                attach_files=True, embed_links=True, add_reactions=True,
                read_message_history=True, manage_messages=True, use_external_emojis=True,
            )
            
            await channel.set_permissions(everyone_role, overwrite=everyone_overwrites)
            await channel.set_permissions(bot_member, overwrite=bot_overwrites)
            
        except Exception as e:
            print(f"❌ Permission error: {e}")

    async def __check_ratelimit(self, message: discord.Message):
        if retry := self.__mratelimiter[message.author].is_ratelimited(message.author):
            await message.reply(embed=discord.Embed(
                color=discord.Color.red(),
                description=f"**You are too fast. Retry after `{retry:.2f}` seconds.**"
            ))
            return False

        elif retry := self.__gratelimiter[message.guild].is_ratelimited(message.guild):
            await message.reply(embed=discord.Embed(
                color=discord.Color.red(),
                description=f"**Many submissions from this server. Retry after `{retry:.2f}` seconds.**"
            ))
            return False
        return True

    @Cog.listener()
    async def on_message(self, message: discord.Message):
        if not all((message.guild, not message.author.bot, message.channel.id in self.bot.cache.ssverify_channels)):
            return

        record = await SSVerify.get_or_none(channel_id=message.channel.id)
        if not record:
            return self.bot.cache.ssverify_channels.discard(message.channel.id)

        await self.__ensure_channel_permissions(message.channel)

        if "tourney-mod" in (role.name.lower() for role in message.author.roles):
            return

        ctx: Context = await self.bot.get_context(message)
        _e = discord.Embed(color=discord.Color.red())

        with suppress(discord.HTTPException):
            if await record.is_user_verified(message.author.id):
                _e.description = "**Your screenshots are already verified, move to next step.**"
                return await ctx.reply(embed=_e)

            if not (attachments := self.__valid_attachments(message)):
                _e.description = "**Send screenshots in `png/jpg/jpeg` format only.**"
                return await ctx.reply(embed=_e)

            if not await self.__check_ratelimit(message):
                return

            if len(attachments) > record.required_ss:
                _e.description = f"**Send `{record.required_ss}` screenshots only (you sent `{len(attachments)}`).**"
                return await ctx.reply(embed=_e)

            _e.color = discord.Color.yellow()
            _e.description = f"Processing your {plural(attachments):screenshot|screenshots}... ⏳"
            m: discord.Message = await message.reply(embed=_e)

            start_at = self.bot.current_time

            # Process with Tesseract OCR only
            async with self.__verify_lock:
                _ocr = []
                for attachment in attachments:
                    result = await self.verify_screenshot_ocr(attachment.proxy_url, record, ctx)
                    _ocr.append(result)

            complete_at = self.bot.current_time

            embed = await self.__verify_screenshots(ctx, record, _ocr)
            
            # Update stats
            self.stats['total_verified'] += 1
            today = datetime.utcnow().date()
            if today > self.stats['last_reset']:
                self.stats['today_verified'] = 0
                self.stats['last_reset'] = today
            self.stats['today_verified'] += 1
            
            embed.set_footer(text=f"Time: {humanize.precisedelta(complete_at-start_at)} | Love from ScrimX❤️")
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
                    _e.title = "Screenshot Verification Complete"
                    _e.url, _e.description = message.jump_url, record.success_message
                    return await message.reply(embed=_e)

                _e.description = f"{ctx.author.mention} Your screenshots are verified, move to next step."
                await message.reply(embed=_e)

    async def __verify_screenshots(self, ctx: Context, record: SSVerify, _ocr: List[ImageResponse]) -> discord.Embed:
        _e = discord.Embed(color=self.bot.color, description="")

        for _ in _ocr:
            # Enhanced duplicate detection
            if not record.allow_same:
                # Exact hash check
                b, t = await record._match_for_duplicate(_.dhash, _.phash, ctx.author.id)
                if b:
                    _e.description += f"{record.emoji(False)} | {t}"
                    continue
                
                # Similarity check for near-duplicates
                existing_images = await record.data.filter(author_id=ctx.author.id).all()
                is_similar = False
                
                for existing in existing_images:
                    similarity = self.calculate_hash_similarity(_.phash, existing.phash)
                    
                    if similarity >= 95.0:
                        _e.description += (
                            f"{record.emoji(False)} | **Duplicate Image Detected!**\n"
                            f"└─ {similarity:.1f}% similar to previous submission.\n"
                        )
                        is_similar = True
                        print(f"⚠️ Similar image: {similarity:.1f}%")
                        break
                
                if is_similar:
                    continue

            # Check if validation passed
            is_valid = "VALID: YES" in _.text
            
            if is_valid:
                _e.description += f"{record.emoji(True)} | Successfully Verified.\n"
                await record._add_to_data(ctx, _)
            else:
                # Extract first failure reason
                lines = _.text.split('\n')
                reason = "Verification failed"
                for line in lines:
                    if '❌' in line:
                        reason = line.replace('❌', '').strip()
                        break
                _e.description += f"{record.emoji(False)} | {reason}\n"

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

    async def setup_ss_channel_permissions(self, channel: discord.TextChannel) -> bool:
        """Setup channel permissions for SS Verify"""
        try:
            everyone_role = channel.guild.default_role
            bot_member = channel.guild.me
            
            everyone_overwrites = discord.PermissionOverwrite(
                view_channel=True, read_messages=True, send_messages=True,
                attach_files=True, add_reactions=True,
                read_message_history=False, embed_links=False,
                mention_everyone=False, use_external_emojis=False,
                use_external_stickers=False, manage_messages=False,
                manage_channels=False, manage_webhooks=False,
                create_public_threads=False, create_private_threads=False,
                send_messages_in_threads=False, use_application_commands=False,
            )
            
            bot_overwrites = discord.PermissionOverwrite(
                view_channel=True, read_messages=True, send_messages=True,
                attach_files=True, embed_links=True, add_reactions=True,
                read_message_history=True, manage_messages=True,
                use_external_emojis=True,
            )
            
            await channel.set_permissions(everyone_role, overwrite=everyone_overwrites)
            await channel.set_permissions(bot_member, overwrite=bot_overwrites)
            
            print(f"✅ Permissions configured for #{channel.name}")
            return True
        except discord.Forbidden:
            print(f"❌ Missing permissions for #{channel.name}")
            return False
        except Exception as e:
            print(f"❌ Permission error: {e}")
            return False
